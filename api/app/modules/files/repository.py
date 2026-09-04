"""Persistência do catálogo de arquivos. Todo `sqlalchemy.text()` do módulo
mora aqui — `service.py` só orquestra entidade + repository + `shared/storage`.
"""
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.files.domain.entities import FileRecord

_COLS = (
    "id, organization_id, project_id, sample_id, sample_gene_id, category, original_name, "
    "storage_key, mime_type, size_bytes, sha256, upload_status, created_by, created_at"
)


def _from_row(row: dict[str, Any]) -> FileRecord:
    return FileRecord(**row)


class PgFileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, file_id: UUID) -> FileRecord | None:
        row = (
            await self.session.execute(
                text(f"SELECT {_COLS} FROM files WHERE id = :id"), {"id": str(file_id)}
            )
        ).mappings().first()
        return _from_row(dict(row)) if row is not None else None

    async def create_pending(self, file: FileRecord) -> None:
        await self.session.execute(
            text(
                "INSERT INTO files (id, organization_id, project_id, sample_id, sample_gene_id, "
                "category, original_name, storage_key, mime_type, size_bytes, upload_status) "
                "VALUES (:id, :org, :proj, :samp, :gene, :cat, :name, :key, :mime, :size, "
                "'pending')"
            ),
            {
                "id": str(file.id),
                "org": str(file.organization_id),
                "proj": str(file.project_id) if file.project_id else None,
                "samp": str(file.sample_id) if file.sample_id else None,
                "gene": str(file.sample_gene_id) if file.sample_gene_id else None,
                "cat": file.category,
                "name": file.original_name,
                "key": file.storage_key,
                "mime": file.mime_type,
                "size": file.size_bytes,
            },
        )

    async def mark_failed(self, file_id: UUID) -> None:
        await self.session.execute(
            text("UPDATE files SET upload_status = 'failed' WHERE id = :id"),
            {"id": str(file_id)},
        )

    async def mark_uploaded(self, file_id: UUID, *, size_bytes: int | None, sha256: str | None) -> FileRecord:
        row = (
            await self.session.execute(
                text(
                    "UPDATE files SET upload_status = 'uploaded', size_bytes = :size, "
                    "sha256 = COALESCE(:sha, sha256) WHERE id = :id "
                    f"RETURNING {_COLS}"
                ),
                {"size": size_bytes, "sha": sha256, "id": str(file_id)},
            )
        ).mappings().first()
        return _from_row(dict(row))

    async def gene_belongs_to_sample(self, sample_gene_id: UUID, sample_id: UUID) -> bool:
        row = (
            await self.session.execute(
                text("SELECT 1 FROM sample_genes WHERE id = :g AND sample_id = :s"),
                {"g": str(sample_gene_id), "s": str(sample_id)},
            )
        ).first()
        return row is not None

    async def list_files(
        self,
        project_id: UUID | None,
        sample_id: UUID | None,
        sample_gene_id: UUID | None = None,
    ) -> list[FileRecord]:
        rows = (
            await self.session.execute(
                text(
                    f"SELECT {_COLS} FROM files "
                    "WHERE (CAST(:proj AS uuid) IS NULL OR project_id = CAST(:proj AS uuid)) "
                    "  AND (CAST(:samp AS uuid) IS NULL OR sample_id = CAST(:samp AS uuid)) "
                    "  AND (CAST(:gene AS uuid) IS NULL "
                    "       OR sample_gene_id = CAST(:gene AS uuid)) "
                    "ORDER BY created_at DESC"
                ),
                {
                    "proj": str(project_id) if project_id else None,
                    "samp": str(sample_id) if sample_id else None,
                    "gene": str(sample_gene_id) if sample_gene_id else None,
                },
            )
        ).mappings().all()
        return [_from_row(dict(r)) for r in rows]

    async def delete(self, file_id: UUID) -> None:
        await self.session.execute(text("DELETE FROM files WHERE id = :id"), {"id": str(file_id)})
