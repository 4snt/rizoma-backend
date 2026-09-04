"""Catálogo de arquivos.

ADR-001: a API NUNCA toca o corpo do arquivo. Ela assina a URL, o browser fala
direto com o MinIO, e depois volta aqui para confirmar. O `confirm` faz um HEAD
real no storage — sem isso, um cliente poderia registrar metadados de um upload
que nunca aconteceu, e o catálogo passaria a mentir.
"""
from uuid import UUID

from fastapi import HTTPException, status

from app.modules.files.domain.entities import FileRecord
from app.modules.files.repository import PgFileRepository
from app.shared import storage
from app.shared.context import Ctx
from app.shared.ids import new_id

from .schemas import FileOut, PresignRequest, PresignResponse

_bucket_ready = False


def _ensure_bucket_once() -> None:
    """Preguiçoso de propósito: chamar no import quebraria qualquer teste/boot
    que rode sem MinIO no ar."""
    global _bucket_ready
    if not _bucket_ready:
        storage.ensure_bucket()
        _bucket_ready = True


async def _require_file(repo: PgFileRepository, file_id: UUID) -> FileRecord:
    file = await repo.get(file_id)
    if file is None:
        # RLS já filtra por organização: um arquivo de outra org é indistinguível
        # de um inexistente. É o comportamento desejado.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arquivo não encontrado.")
    return file


async def presign(ctx: Ctx, req: PresignRequest) -> PresignResponse:
    ctx.require("file:write")
    _ensure_bucket_once()
    repo = PgFileRepository(ctx.session)

    if req.sample_gene_id is not None:
        # Gene é sub-recurso da amostra: sem sample_id não há como provar que
        # o gene é dela — e um gene de OUTRA amostra é indistinguível de um
        # inexistente (RLS + WHERE sample_id), logo 404.
        if req.sample_id is None:
            raise HTTPException(422, "sample_gene_id exige sample_id.")
        if not await repo.gene_belongs_to_sample(req.sample_gene_id, req.sample_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Gene não encontrado nesta amostra.")

    file_id = new_id()
    # O id entra na chave para garantir unicidade: dois uploads do mesmo nome na
    # mesma amostra não podem colidir no UNIQUE de storage_key.
    key = storage.build_key(
        ctx.org_id,
        req.project_id,
        req.sample_id or "_",
        f"{file_id}-{req.original_name}",
    )
    content_type = req.mime_type or "application/octet-stream"

    await repo.create_pending(
        FileRecord(
            id=file_id,
            organization_id=ctx.org_id,
            project_id=req.project_id,
            sample_id=req.sample_id,
            sample_gene_id=req.sample_gene_id,
            category=req.category,
            original_name=req.original_name,
            storage_key=key,
            mime_type=content_type,
            size_bytes=req.size_bytes,
        )
    )

    presigned = storage.presign_upload(key, content_type=content_type)
    return PresignResponse(
        file_id=file_id,
        upload_url=presigned.url,
        fields=presigned.fields,
        storage_key=presigned.storage_key,
    )


async def confirm(ctx: Ctx, file_id: UUID, sha256: str | None) -> FileOut:
    ctx.require("file:write")
    _ensure_bucket_once()
    repo = PgFileRepository(ctx.session)

    file = await _require_file(repo, file_id)
    meta = storage.head(file.storage_key)

    if meta is None:
        await repo.mark_failed(file_id)
        # Commit antes de estourar: o 400 não pode desfazer a marcação de falha.
        await ctx.session.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Upload não encontrado no storage."
        )

    updated = await repo.mark_uploaded(file_id, size_bytes=meta["size_bytes"], sha256=sha256)
    return FileOut(**updated.to_dict())


async def download_url(ctx: Ctx, file_id: UUID) -> str:
    ctx.require("file:read")
    repo = PgFileRepository(ctx.session)
    file = await _require_file(repo, file_id)
    return storage.presign_download(file.storage_key)


async def list_files(
    ctx: Ctx,
    project_id: UUID | None,
    sample_id: UUID | None,
    sample_gene_id: UUID | None = None,
) -> list[FileOut]:
    ctx.require("file:read")
    repo = PgFileRepository(ctx.session)
    files = await repo.list_files(project_id, sample_id, sample_gene_id)
    return [FileOut(**f.to_dict()) for f in files]


async def delete_file(ctx: Ctx, file_id: UUID) -> None:
    ctx.require("file:write")
    repo = PgFileRepository(ctx.session)
    file = await _require_file(repo, file_id)
    storage.delete(file.storage_key)
    await repo.delete(file_id)
