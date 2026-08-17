"""Contratos do módulo de laboratório.

A regra que molda estes schemas (§5.5 do plano): **um resultado nunca é um
número solto.** `unit` é obrigatório no schema, não só no banco — um "0,03" sem
unidade é indistinguível de um erro de digitação, e um laudo assinado em cima
disso é um laudo falso.
"""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ResultCreate(BaseModel):
    analyte: str = Field(min_length=1)
    method: str | None = None
    value_numeric: Decimal | None = None
    value_text: str | None = None
    # Obrigatório de propósito: ausência vira 422 no FastAPI, antes de tocar o banco.
    unit: str = Field(min_length=1)
    lod: Decimal | None = None
    loq: Decimal | None = None
    uncertainty: Decimal | None = None


class ResultCorrect(BaseModel):
    """Correção = versão nova. Nada é sobrescrito.

    `change_reason` é opcional AQUI para que a ausência vire um 400 com mensagem
    de domínio no service, em vez de um 422 genérico de validação — a exigência
    de justificativa é uma regra da ISO 17025, não um detalhe de formulário.
    """
    value_numeric: Decimal | None = None
    value_text: str | None = None
    unit: str | None = None
    lod: Decimal | None = None
    loq: Decimal | None = None
    uncertainty: Decimal | None = None
    change_reason: str | None = None


class ResultReview(BaseModel):
    status: str = Field(default="approved", pattern="^(approved|retracted)$")
    note: str | None = None


class VersionOut(BaseModel):
    id: UUID
    version: int
    value_numeric: Decimal | None = None
    value_text: str | None = None
    unit: str
    lod: Decimal | None = None
    loq: Decimal | None = None
    uncertainty: Decimal | None = None
    below_lod: bool
    status: str
    supersedes: UUID | None = None
    change_reason: str | None = None
    created_by: UUID
    reviewed_by: UUID | None = None
    created_at: datetime
    # Como o valor deve APARECER num laudo. "<0.05" é um resultado válido:
    # tratá-lo como 0 ou como null falsifica o laudo.
    display_value: str


class ResultOut(BaseModel):
    id: UUID
    sample_id: UUID
    analyte: str
    method: str | None = None
    created_at: datetime
    current: VersionOut
    history: list[VersionOut]


class ResultListItemOut(BaseModel):
    """Só a versão corrente (sem `history`) + código de amostra/projeto —
    alimenta a listagem top-level `GET /results` (projeto e amostra viram
    agregador exibido, não pré-requisito de rota; ver
    `/samples/{id}/results`, que continua existindo pra quem já está no
    contexto de uma amostra)."""

    id: UUID
    sample_id: UUID
    sample_code: str
    project_id: UUID
    project_code: str
    analyte: str
    method: str | None = None
    created_at: datetime
    current: VersionOut
