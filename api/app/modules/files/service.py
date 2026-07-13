"""Catálogo de arquivos.

ADR-001: a API NUNCA toca o corpo do arquivo. Ela assina a URL, o browser fala
direto com o MinIO, e depois volta aqui para confirmar. O `confirm` faz um HEAD
real no storage — sem isso, um cliente poderia registrar metadados de um upload
que nunca aconteceu, e o catálogo passaria a mentir.
"""
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared import storage
from app.shared.context import Ctx
from app.shared.ids import new_id

from .schemas import FileOut, PresignRequest, PresignResponse

_bucket_ready = False

FILE_COLUMNS = (
    "id, organization_id, project_id, sample_id, category, original_name, "
    "storage_key, mime_type, size_bytes, sha256, upload_status, created_by, created_at"
)


def _ensure_bucket_once() -> None:
    """Preguiçoso de propósito: chamar no import quebraria qualquer teste/boot
    que rode sem MinIO no ar."""
    global _bucket_ready
    if not _bucket_ready:
        storage.ensure_bucket()
        _bucket_ready = True


async def _get_file(session: AsyncSession, file_id: UUID) -> dict:
    row = (
        await session.execute(
            text(f"SELECT {FILE_COLUMNS} FROM files WHERE id = :id"), {"id": str(file_id)}
        )
    ).mappings().first()
    if row is None:
        # RLS já filtra por organização: um arquivo de outra org é indistinguível
        # de um inexistente. É o comportamento desejado.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arquivo não encontrado.")
    return dict(row)


async def presign(ctx: Ctx, req: PresignRequest) -> PresignResponse:
    ctx.require("file:write")
    _ensure_bucket_once()

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

    await ctx.session.execute(
        text(
            "INSERT INTO files (id, organization_id, project_id, sample_id, category, "
            "original_name, storage_key, mime_type, size_bytes, upload_status) "
            "VALUES (:id, :org, :proj, :samp, :cat, :name, :key, :mime, :size, 'pending')"
        ),
        {
            "id": str(file_id),
            "org": str(ctx.org_id),
            "proj": str(req.project_id),
            "samp": str(req.sample_id) if req.sample_id else None,
            "cat": req.category,
            "name": req.original_name,
            "key": key,
            "mime": content_type,
            "size": req.size_bytes,
        },
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

    row = await _get_file(ctx.session, file_id)
    meta = storage.head(row["storage_key"])

    if meta is None:
        await ctx.session.execute(
            text("UPDATE files SET upload_status = 'failed' WHERE id = :id"),
            {"id": str(file_id)},
        )
        # Commit antes de estourar: o 400 não pode desfazer a marcação de falha.
        await ctx.session.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Upload não encontrado no storage."
        )

    updated = (
        await ctx.session.execute(
            text(
                "UPDATE files SET upload_status = 'uploaded', size_bytes = :size, "
                "sha256 = COALESCE(:sha, sha256) WHERE id = :id "
                f"RETURNING {FILE_COLUMNS}"
            ),
            {"size": meta["size_bytes"], "sha": sha256, "id": str(file_id)},
        )
    ).mappings().first()
    return FileOut(**dict(updated))


async def download_url(ctx: Ctx, file_id: UUID) -> str:
    ctx.require("file:read")
    row = await _get_file(ctx.session, file_id)
    return storage.presign_download(row["storage_key"])


async def list_files(
    ctx: Ctx, project_id: UUID | None, sample_id: UUID | None
) -> list[FileOut]:
    ctx.require("file:read")
    rows = (
        await ctx.session.execute(
            text(
                f"SELECT {FILE_COLUMNS} FROM files "
                "WHERE (CAST(:proj AS uuid) IS NULL OR project_id = CAST(:proj AS uuid)) "
                "  AND (CAST(:samp AS uuid) IS NULL OR sample_id = CAST(:samp AS uuid)) "
                "ORDER BY created_at DESC"
            ),
            {
                "proj": str(project_id) if project_id else None,
                "samp": str(sample_id) if sample_id else None,
            },
        )
    ).mappings().all()
    return [FileOut(**dict(r)) for r in rows]


async def delete_file(ctx: Ctx, file_id: UUID) -> None:
    ctx.require("file:write")
    row = await _get_file(ctx.session, file_id)
    storage.delete(row["storage_key"])
    await ctx.session.execute(
        text("DELETE FROM files WHERE id = :id"), {"id": str(file_id)}
    )
