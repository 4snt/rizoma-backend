"""Contratos do módulo de laudos."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ReportCreate(BaseModel):
    title: str = Field(min_length=1)
    code: str | None = None


class ReportOut(BaseModel):
    id: UUID
    project_id: UUID
    code: str
    version: int
    title: str
    status: str
    sha256: str | None = None
    storage_key: str | None = None
    signed_by: UUID | None = None
    signed_at: datetime | None = None
    created_at: datetime
    content: dict | None = None
    download_url: str | None = None


class ReportListItem(BaseModel):
    id: UUID
    project_id: UUID
    code: str
    version: int
    title: str
    status: str
    sha256: str | None = None
    signed_at: datetime | None = None
    created_at: datetime


class VerifyOut(BaseModel):
    """Resposta PÚBLICA. Só o suficiente para provar autenticidade.

    Nada de resultados, nada de cliente, nada de amostras: quem escaneia o QR
    pode ser qualquer pessoa do mundo. O que ela precisa saber é se o papel na
    mão dela é mesmo o documento que este laboratório emitiu.
    """
    valid: bool
    code: str | None = None
    version: int | None = None
    project: str | None = None
    signed_at: datetime | None = None
    organization: str | None = None
    detail: str | None = None
