"""Contratos de entrada e saída do módulo LIMS (Pydantic v2)."""
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
OrganismType = Literal["bacteria", "fungo", "outro"]
# Descritores de morfologia de colônia, vocabulário fechado (padrão Bergey).
ColoniaForma = Literal[
    "circular", "irregular", "filamentosa", "rizoide", "fusiforme", "puntiforme",
]
ColoniaElevacao = Literal[
    "plana", "elevada", "convexa", "pulvinada", "umbonada", "crateriforme",
]
ColoniaMargem = Literal["inteira", "ondulada", "lobada", "filiforme", "crespa"]
ColoniaTextura = Literal["lisa", "rugosa", "mucoide", "seca", "granular", "viscosa"]
ColoniaOpacidade = Literal["opaca", "translucida", "transparente"]
GenePurpose = Literal["identificacao", "resistencia", "producao_enzima", "outro"]
# Caracterização microscópica do isolado.
GramStain = Literal["positiva", "negativa", "variavel", "nao_aplicavel"]
CellShape = Literal[
    "bacilo", "coco", "cocobacilo", "espirilo", "vibriao", "filamentoso",
    "leveduriforme", "hifa", "outro",
]
Motility = Literal["movel", "imovel", "nao_testado"]
# Estoque físico de alíquotas.
StorageMethod = Literal[
    "glicerol_-80", "glicerol_-20", "liofilizado", "placa_4c",
    "oleo_mineral", "agua_esteril", "outro",
]
AliquotStatus = Literal["disponivel", "consumida", "descartada", "contaminada"]

# Alfabeto IUPAC de nucleotídeos (inclui ambiguidades e gap).
_NUCLEOTIDE_ALPHABET = frozenset("ACGTURYKMSWBDHVN-")


def _split_fasta(values: Any) -> Any:
    """`model_validator(mode='before')` compartilhado: se `sequence` vier
    como FASTA colado (começa com `>`), a primeira linha vira
    `sequence_header` — só se o header não veio explícito no payload."""
    if not isinstance(values, dict):
        return values
    seq = values.get("sequence")
    if isinstance(seq, str) and seq.lstrip().startswith(">"):
        header, _, rest = seq.lstrip().partition("\n")
        if values.get("sequence_header") is None:
            values = {**values, "sequence_header": header[1:].strip() or None}
        values = {**values, "sequence": rest}
    return values


def _clean_sequence(value: str | None) -> str | None:
    """Normaliza sequência: tira espaços, quebras de linha, dígitos (numeração
    de linha do GenBank) e `*` final; maiúsculas; vazio → None; caractere
    fora do alfabeto IUPAC → ValueError (vira 422)."""
    if value is None:
        return None
    cleaned = "".join(ch for ch in value if not ch.isspace() and not ch.isdigit())
    cleaned = cleaned.rstrip("*").upper()
    if not cleaned:
        return None
    invalid = sorted(set(cleaned) - _NUCLEOTIDE_ALPHABET)
    if invalid:
        raise ValueError(
            "Sequência contém caracteres inválidos: "
            + ", ".join(invalid)
            + ". Só o alfabeto IUPAC de nucleotídeos (ACGTURYKMSWBDHVN-) é aceito."
        )
    return cleaned


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
    status: ProjectStatus
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
    # Dados biológicos, opcionais — só fazem sentido pra isolados (matrix
    # cultura_microbiana e afins). Podem entrar já na criação ou via
    # PATCH /samples/{id} depois.
    organism_type: OrganismType | None = None
    colonia_forma: ColoniaForma | None = None
    colonia_elevacao: ColoniaElevacao | None = None
    colonia_margem: ColoniaMargem | None = None
    colonia_cor: str | None = None
    colonia_textura: ColoniaTextura | None = None
    colonia_tamanho_mm: float | None = Field(default=None, ge=0)
    colonia_opacidade: ColoniaOpacidade | None = None
    # Registro do isolado: identidade da cepa, origem, cultivo, microscopia.
    isolation_source: str | None = None
    host_species: str | None = None
    host_cultivar: str | None = None
    collection_site: str | None = None
    isolated_at: date | None = None
    culture_medium: str | None = None
    incubation_temp_c: float | None = None
    incubation_hours: float | None = None
    gram_stain: GramStain | None = None
    cell_shape: CellShape | None = None
    motility: Motility | None = None


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
    organism_type: OrganismType | None = None
    colonia_forma: ColoniaForma | None = None
    colonia_elevacao: ColoniaElevacao | None = None
    colonia_margem: ColoniaMargem | None = None
    colonia_cor: str | None = None
    colonia_textura: ColoniaTextura | None = None
    colonia_tamanho_mm: float | None = None
    colonia_opacidade: ColoniaOpacidade | None = None
    isolation_source: str | None = None
    host_species: str | None = None
    host_cultivar: str | None = None
    collection_site: str | None = None
    isolated_at: date | None = None
    culture_medium: str | None = None
    incubation_temp_c: float | None = None
    incubation_hours: float | None = None
    gram_stain: GramStain | None = None
    cell_shape: CellShape | None = None
    motility: Motility | None = None


class SampleUpdate(BaseModel):
    """PATCH parcial da amostra — descritivo (morfologia, isolado, notas,
    posição). Separado de `SampleTransition`, que é sobre custódia/status e
    gera evento encadeado; aqui nada mexe em `status`/`code`/`matrix`.

    Só o que veio setado no payload é gravado (`exclude_unset`); mandar
    `null` explicitamente limpa o campo."""

    treatment_group: str | None = None
    replicate: int | None = None
    notes: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    occurred_at: datetime | None = None
    organism_type: OrganismType | None = None
    colonia_forma: ColoniaForma | None = None
    colonia_elevacao: ColoniaElevacao | None = None
    colonia_margem: ColoniaMargem | None = None
    colonia_cor: str | None = None
    colonia_textura: ColoniaTextura | None = None
    colonia_tamanho_mm: float | None = Field(default=None, ge=0)
    colonia_opacidade: ColoniaOpacidade | None = None
    isolation_source: str | None = None
    host_species: str | None = None
    host_cultivar: str | None = None
    collection_site: str | None = None
    isolated_at: date | None = None
    culture_medium: str | None = None
    incubation_temp_c: float | None = None
    incubation_hours: float | None = None
    gram_stain: GramStain | None = None
    cell_shape: CellShape | None = None
    motility: Motility | None = None

    @model_validator(mode="after")
    def _lat_lon_juntos(self) -> "SampleUpdate":
        # `geom` é um ponto só: não dá pra atualizar metade dele. Ou vêm os
        # dois (ambos número → grava; ambos null → limpa), ou nenhum.
        has_lat = "lat" in self.model_fields_set
        has_lon = "lon" in self.model_fields_set
        if has_lat != has_lon:
            raise ValueError("lat e lon devem ser enviados juntos.")
        if has_lat and (self.lat is None) != (self.lon is None):
            raise ValueError("lat e lon devem ser ambos números ou ambos null.")
        return self


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


# ── Testes bioquímicos/enzimáticos (catálogo aberto) ───────────────────────
# test_name é texto livre de propósito: não há lista fixa de testes,
# qualquer teste de bancada novo entra sem precisar de migration.
class SampleTestCreate(BaseModel):
    test_name: str = Field(min_length=1, max_length=120)
    result: str | None = None
    # 'qualitativo' (+/-/++/-+/N em `result`) ou 'quantitativo'
    # (`result_value` + `result_unit`). Livre de propósito — sem enum no
    # banco, mesmo catálogo aberto do `test_name`.
    result_type: str | None = Field(default=None, max_length=20)
    result_value: float | None = None
    result_unit: str | None = Field(default=None, max_length=20)
    method: str | None = None
    tested_at: date | None = None
    notes: str | None = None


class SampleTestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sample_id: UUID
    test_name: str
    result: str | None = None
    result_type: str | None = None
    result_value: float | None = None
    result_unit: str | None = None
    method: str | None = None
    tested_at: date | None = None
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime


# ── Genes sequenciados ──────────────────────────────────────────────────
# Metadado + resultado + a sequência em si (FASTA colado é aceito: header
# vira `sequence_header`, corpo é normalizado) + resumo do BLAST.
class _SampleGeneSequenceMixin(BaseModel):
    sequence: str | None = None
    sequence_header: str | None = None
    primer_forward: str | None = None
    primer_reverse: str | None = None
    blast_top_hit: str | None = None
    blast_identity_pct: float | None = Field(default=None, ge=0, le=100)
    blast_coverage_pct: float | None = Field(default=None, ge=0, le=100)
    blast_hit_accession: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _fasta_header(cls, values: Any) -> Any:
        return _split_fasta(values)

    @field_validator("sequence")
    @classmethod
    def _normalize_sequence(cls, value: str | None) -> str | None:
        return _clean_sequence(value)


class SampleGeneCreate(_SampleGeneSequenceMixin):
    gene: str = Field(min_length=1, max_length=60)
    purpose: GenePurpose
    result: str | None = None
    ncbi_accession: str | None = None
    method: str | None = None
    tested_at: date | None = None
    notes: str | None = None


class SampleGeneUpdate(_SampleGeneSequenceMixin):
    """PATCH parcial do gene — tudo opcional, só o que veio setado é gravado."""

    gene: str | None = Field(default=None, min_length=1, max_length=60)
    purpose: GenePurpose | None = None
    result: str | None = None
    ncbi_accession: str | None = None
    method: str | None = None
    tested_at: date | None = None
    notes: str | None = None


class SampleGeneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sample_id: UUID
    gene: str
    purpose: GenePurpose
    result: str | None = None
    ncbi_accession: str | None = None
    method: str | None = None
    tested_at: date | None = None
    notes: str | None = None
    sequence: str | None = None
    sequence_header: str | None = None
    # Calculado pelo banco (coluna gerada) — nunca diverge de `sequence`.
    sequence_length: int | None = None
    primer_forward: str | None = None
    primer_reverse: str | None = None
    blast_top_hit: str | None = None
    blast_identity_pct: float | None = None
    blast_coverage_pct: float | None = None
    blast_hit_accession: str | None = None
    created_by: UUID | None = None
    created_at: datetime


# ── Alíquotas (estoque físico) ──────────────────────────────────────────
# Tubo/placa de verdade no freezer. `label` é único por amostra: dois tubos
# com o mesmo rótulo na mesma cepa é erro de cadastro, não dois tubos.
class SampleAliquotCreate(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    storage_method: StorageMethod
    freezer: str | None = None
    box: str | None = None
    position: str | None = None
    stored_at: date | None = None
    status: AliquotStatus = "disponivel"
    notes: str | None = None


class SampleAliquotUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=40)
    storage_method: StorageMethod | None = None
    freezer: str | None = None
    box: str | None = None
    position: str | None = None
    stored_at: date | None = None
    status: AliquotStatus | None = None
    notes: str | None = None


class SampleAliquotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sample_id: UUID
    label: str
    storage_method: StorageMethod
    freezer: str | None = None
    box: str | None = None
    position: str | None = None
    stored_at: date | None = None
    status: AliquotStatus
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
