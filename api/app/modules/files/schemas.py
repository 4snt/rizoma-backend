"""Contratos do catálogo de arquivos (ADR-001).

Nenhum schema aqui carrega bytes. O corpo do arquivo nunca passa pela API —
só a chave, a URL assinada e o metadado.
"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

FileCategory = Literal[
    "fastq_r1", "fastq_r2", "phyloseq", "result",
    "report", "field_photo", "document", "other",
    # Registro de isolados: sequência/cromatograma ligados a um gene, gel e
    # foto de colônia ligados à amostra.
    "fasta", "chromatogram", "gel_image", "colony_photo",
]


class PresignRequest(BaseModel):
    project_id: UUID
    sample_id: UUID | None = None
    # Vínculo opcional com um gene específico da amostra (FASTA/cromatograma
    # do 16S, por exemplo). Exige `sample_id` e o gene precisa ser dela.
    sample_gene_id: UUID | None = None
    category: FileCategory
    original_name: str = Field(min_length=1, max_length=512)
    mime_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class PresignResponse(BaseModel):
    file_id: UUID
    upload_url: str
    fields: dict
    storage_key: str


class ConfirmRequest(BaseModel):
    sha256: str | None = None


class FileOut(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID | None
    sample_id: UUID | None
    sample_gene_id: UUID | None = None
    category: str
    original_name: str
    storage_key: str
    mime_type: str | None
    size_bytes: int | None
    sha256: str | None
    upload_status: str
    created_by: UUID | None
    created_at: datetime


class DownloadResponse(BaseModel):
    url: str
