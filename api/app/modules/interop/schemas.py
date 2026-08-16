"""Contratos de interoperabilidade — webhooks + import/export de amostras
(tcc-rizoma#10)."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl

# Vocabulário fechado de propósito: um assinante não devia conseguir se
# inscrever num evento que a gente ainda não emite — silenciosamente nunca
# recebendo nada é pior do que a validação recusar na hora do cadastro.
WEBHOOK_EVENT_TYPES = (
    "job.completed",
    "job.failed",
    "sample.created",
)


class WebhookSubscriptionCreate(BaseModel):
    url: HttpUrl
    event_types: list[str] = Field(min_length=1)


class WebhookSubscriptionOut(BaseModel):
    id: UUID
    organization_id: UUID
    url: str
    event_types: list[str]
    is_active: bool
    created_by: UUID | None
    created_at: datetime
    # secret nunca sai no Out — só é mostrado uma vez, no create.


class WebhookSubscriptionCreated(WebhookSubscriptionOut):
    secret: str


class SampleImportRowError(BaseModel):
    row: int
    code: str | None
    error: str


class SampleImportResult(BaseModel):
    created: int
    errors: list[SampleImportRowError]
