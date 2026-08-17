"""Contratos de entrada e saída do módulo LIMS (Pydantic v2)."""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MarkerType = Literal["16S", "ITS", "RNA"]
ProjectStatus = Literal[
    "draft", "planning", "approved", "in_progress",
    "under_review", "completed", "cancelled", "archived",
]
SampleMatrix = Literal[
    "solo", "sedimento", "agua", "tecido_vegetal", "raiz", "folha",
    "biomassa", "cultura_microbiana", "dna", "rna", "extrato",
    "biochar", "formulado", "substrato",
]
SampleStatus = Literal[
    "planned", "collected", "in_transit", "received", "accepted",
    "rejected", "processing", "analyzed", "stored", "consumed", "disposed",
]
CustodyEventType = Literal[
    "coleta", "transporte", "recebimento", "transferencia",
    "processamento", "armazenamento", "retirada", "devolucao", "descarte",
]


# ── Projetos ────────────────────────────────────────────────────────────
# Não existe mais CustomerCreate/CustomerOut. O "pesquisador" de um projeto
# é sempre um organization_member (conta Google, papel real) — gerenciado
# pelo módulo identity (GET /api/v2/identity/members), não um contato solto
# criado por aqui.
class ProjectCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    customer_user_id: UUID | None = None
    marker_type: MarkerType | None = None
    dada2_params: dict[str, Any] = Field(default_factory=dict)
    # Catálogo de análise escolhido na criação (ex: [{"analysis_type": "deseq2",
    # "charts": ["volcano", "ma_plot"]}]) — shape solto de propósito, quem
    # valida o vocabulário é o frontend (lib/analyses-catalog.ts).
    analyses: list[dict[str, Any]] = Field(default_factory=list)


class ProjectStatusUpdate(BaseModel):
    status: ProjectStatus


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    customer_user_id: UUID | None = None
    code: str
    name: str
    description: str
    marker_type: MarkerType | None = None
    status: ProjectStatus
    dada2_params: dict[str, Any] = Field(default_factory=dict)
    analyses: list[dict[str, Any]] = Field(default_factory=list)
    created_by: UUID | None = None
    created_at: datetime


# ── Amostras ────────────────────────────────────────────────────────────
class SampleCreate(BaseModel):
    # O tablet em campo gera o UUIDv7 offline; o servidor respeita.
    id: UUID | None = None
    code: str = Field(min_length=1, max_length=64)
    matrix: SampleMatrix
    treatment_group: str | None = None
    replicate: int | None = None
    status: SampleStatus = "planned"
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    # Quando foi coletado (campo) — distinto de recorded_at (chegada ao servidor).
    occurred_at: datetime | None = None
    notes: str | None = None


class SampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    project_id: UUID
    code: str
    matrix: SampleMatrix
    treatment_group: str | None = None
    replicate: int | None = None
    status: SampleStatus
    lat: float | None = None
    lon: float | None = None
    collected_by: UUID | None = None
    occurred_at: datetime | None = None
    recorded_at: datetime
    notes: str | None = None
    created_at: datetime


class SampleListItemOut(SampleOut):
    """`SampleOut` + código/nome do projeto — só existe pra alimentar a
    listagem top-level `GET /samples` (projeto vira agregador exibido, não
    pré-requisito de rota; ver `/projects/{id}/samples`, que continua
    existindo pra quem já está no contexto de um projeto)."""

    project_code: str
    project_name: str


class SampleTransition(BaseModel):
    to_status: SampleStatus
    to_custodian: UUID | None = None
    occurred_at: datetime | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    temperature_c: float | None = None
    condition: str | None = None
    notes: str | None = None


class CustodyEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sample_id: UUID
    seq: int
    event_type: CustodyEventType
    from_custodian: UUID | None = None
    to_custodian: UUID | None = None
    occurred_at: datetime
    recorded_at: datetime
    temperature_c: float | None = None
    condition: str | None = None
    notes: str | None = None
    prev_hash: str | None = None
    hash: str


class CustodyChainOut(BaseModel):
    sample_id: UUID
    events: list[CustodyEventOut]
    # Recalculado do zero a cada leitura — não é um flag armazenado.
    chain_valid: bool
