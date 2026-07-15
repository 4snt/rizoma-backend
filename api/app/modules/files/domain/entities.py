"""Entidade do catálogo de arquivos (ADR-001).

Nenhuma entidade aqui carrega bytes — só o metadado. O corpo do arquivo nunca
passa pela API, só o MinIO fala com ele diretamente (`shared/storage.py`).
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass
class FileRecord:
    id: UUID
    organization_id: UUID
    project_id: UUID | None
    sample_id: UUID | None
    category: str
    original_name: str
    storage_key: str
    mime_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    upload_status: str = "pending"
    created_by: UUID | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "project_id": self.project_id,
            "sample_id": self.sample_id,
            "category": self.category,
            "original_name": self.original_name,
            "storage_key": self.storage_key,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "upload_status": self.upload_status,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }
