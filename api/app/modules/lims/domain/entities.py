"""Entidades do domínio LIMS: Projeto, Amostra e Evento de Custódia.

Dataclasses com identidade e comportamento, no mesmo espírito de
`app/domain/sample/entities.py` (v1) — não são DTOs de API (isso é
`schemas.py`) nem linhas de banco (isso é `repository.py`).

Não existe mais entidade Cliente/Pesquisador própria — pesquisador é
sempre um `organization_member` (conta Google, papel de verdade), gerido
pelo módulo `identity`. `Project.customer_user_id` referencia esse membro
diretamente; ver ADR de fusão em docs/decisions/.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.modules.lims import custody
from app.modules.lims.domain.value_objects import GeoPoint


@dataclass
class Project:
    id: UUID
    organization_id: UUID
    code: str
    name: str
    description: str = ""
    customer_user_id: UUID | None = None
    status: str = "draft"
    created_by: UUID | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "customer_user_id": self.customer_user_id,
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


@dataclass
class CustodyEvent:
    """Um elo da cadeia de custódia. Nunca é criado solto — sempre via
    `next_in_chain`, que é quem sabe calcular `seq`, `prev_hash` e `hash`."""

    id: UUID
    organization_id: UUID
    sample_id: UUID
    seq: int
    event_type: str
    from_custodian: UUID | None
    to_custodian: UUID | None
    occurred_at: datetime
    prev_hash: str | None
    hash: str
    geo: GeoPoint | None = None
    temperature_c: float | None = None
    condition: str | None = None
    notes: str | None = None
    recorded_at: datetime | None = None

    @classmethod
    def next_in_chain(
        cls,
        *,
        id: UUID,
        organization_id: UUID,
        sample_id: UUID,
        last_event: "CustodyEvent | None",
        target_status: str,
        to_custodian: UUID | None,
        occurred_at: datetime,
        geo: GeoPoint | None = None,
        temperature_c: float | None = None,
        condition: str | None = None,
        notes: str | None = None,
    ) -> "CustodyEvent":
        """Fabrica o próximo evento da cadeia, encadeado ao último via hash.

        `seq` e `prev_hash` derivam do último evento (ou de 1/None se for o
        primeiro); quem detinha a amostra (`last_event.to_custodian`) vira o
        `from_custodian` deste elo — a posse anda um passo adiante.
        """
        seq = (last_event.seq + 1) if last_event else 1
        prev_hash = last_event.hash if last_event else None
        from_custodian = last_event.to_custodian if last_event else None
        event_type = custody.event_type_for(target_status)
        event_hash = custody.compute_hash(
            prev_hash=prev_hash,
            sample_id=sample_id,
            seq=seq,
            event_type=event_type,
            occurred_at=occurred_at,
            from_custodian=from_custodian,
            to_custodian=to_custodian,
        )
        return cls(
            id=id,
            organization_id=organization_id,
            sample_id=sample_id,
            seq=seq,
            event_type=event_type,
            from_custodian=from_custodian,
            to_custodian=to_custodian,
            occurred_at=occurred_at,
            prev_hash=prev_hash,
            hash=event_hash,
            geo=geo,
            temperature_c=temperature_c,
            condition=condition,
            notes=notes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "sample_id": self.sample_id,
            "seq": self.seq,
            "event_type": self.event_type,
            "from_custodian": self.from_custodian,
            "to_custodian": self.to_custodian,
            "occurred_at": self.occurred_at,
            "recorded_at": self.recorded_at,
            "temperature_c": self.temperature_c,
            "condition": self.condition,
            "notes": self.notes,
            "prev_hash": self.prev_hash,
            "hash": self.hash,
        }


@dataclass
class Sample:
    id: UUID
    organization_id: UUID
    project_id: UUID
    code: str
    matrix: str
    status: str
    treatment_group: str | None = None
    replicate: int | None = None
    geo: GeoPoint | None = None
    collected_by: UUID | None = None
    occurred_at: datetime | None = None
    recorded_at: datetime | None = None
    notes: str | None = None
    created_at: datetime | None = None
    # Dados biológicos — só fazem sentido pra isolados (organism_type setado),
    # mas ficam na própria Sample: ela é o agregado, ver módulo docstring.
    organism_type: str | None = None
    colonia_forma: str | None = None
    colonia_elevacao: str | None = None
    colonia_margem: str | None = None
    colonia_cor: str | None = None
    colonia_textura: str | None = None
    colonia_tamanho_mm: float | None = None
    colonia_opacidade: str | None = None
    # Registro do isolado: identidade da cepa, origem/hospedeiro, cultivo,
    # caracterização microscópica.
    isolation_source: str | None = None
    host_species: str | None = None
    host_cultivar: str | None = None
    collection_site: str | None = None
    isolated_at: date | None = None
    culture_medium: str | None = None
    incubation_temp_c: float | None = None
    incubation_hours: float | None = None
    gram_stain: str | None = None
    cell_shape: str | None = None
    motility: str | None = None

    def assert_can_transition_to(self, target_status: str) -> None:
        """Delega à máquina de estados de `custody.py`. Lança
        `custody.InvalidTransition` se a transição não for permitida."""
        custody.assert_transition(self.status, target_status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "project_id": self.project_id,
            "code": self.code,
            "matrix": self.matrix,
            "status": self.status,
            "treatment_group": self.treatment_group,
            "replicate": self.replicate,
            "lat": self.geo.lat if self.geo else None,
            "lon": self.geo.lon if self.geo else None,
            "collected_by": self.collected_by,
            "occurred_at": self.occurred_at,
            "recorded_at": self.recorded_at,
            "notes": self.notes,
            "created_at": self.created_at,
            "organism_type": self.organism_type,
            "colonia_forma": self.colonia_forma,
            "colonia_elevacao": self.colonia_elevacao,
            "colonia_margem": self.colonia_margem,
            "colonia_cor": self.colonia_cor,
            "colonia_textura": self.colonia_textura,
            "colonia_tamanho_mm": self.colonia_tamanho_mm,
            "colonia_opacidade": self.colonia_opacidade,
            "isolation_source": self.isolation_source,
            "host_species": self.host_species,
            "host_cultivar": self.host_cultivar,
            "collection_site": self.collection_site,
            "isolated_at": self.isolated_at,
            "culture_medium": self.culture_medium,
            "incubation_temp_c": self.incubation_temp_c,
            "incubation_hours": self.incubation_hours,
            "gram_stain": self.gram_stain,
            "cell_shape": self.cell_shape,
            "motility": self.motility,
        }


@dataclass
class SampleTest:
    """Um teste bioquímico/enzimático de bancada. Catálogo aberto de
    propósito (`test_name` livre) — mutável, sem trigger de imutabilidade:
    não é elo de custódia legal nem resultado ISO 17025 formal (isso já
    existe em `lab_results`/`result_versions`, módulo `laboratory`)."""

    id: UUID
    organization_id: UUID
    sample_id: UUID
    test_name: str
    result: str | None = None
    # Qualitativo: teste enzimático padrão, resultado em +/-/++/-+/N (ver
    # `result`). Quantitativo: quando dá pra medir de verdade — usa
    # `result_value` (numérico) + `result_unit` em vez de `result`.
    result_type: str | None = None
    result_value: float | None = None
    result_unit: str | None = None
    method: str | None = None
    tested_at: date | None = None
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "sample_id": self.sample_id,
            "test_name": self.test_name,
            "result": self.result,
            "result_type": self.result_type,
            "result_value": self.result_value,
            "result_unit": self.result_unit,
            "method": self.method,
            "tested_at": self.tested_at,
            "notes": self.notes,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class SampleGene:
    """Um gene sequenciado (16S p/ identificação, genes de resistência ou
    produção de enzima). Metadado + resultado + a sequência normalizada e o
    resumo do BLAST. `sequence_length` é calculado pelo banco (coluna
    gerada), por isso nunca é informado na criação."""

    id: UUID
    organization_id: UUID
    sample_id: UUID
    gene: str
    purpose: str
    result: str | None = None
    ncbi_accession: str | None = None
    method: str | None = None
    tested_at: date | None = None
    notes: str | None = None
    sequence: str | None = None
    sequence_header: str | None = None
    sequence_length: int | None = None
    primer_forward: str | None = None
    primer_reverse: str | None = None
    blast_top_hit: str | None = None
    blast_identity_pct: float | None = None
    blast_coverage_pct: float | None = None
    blast_hit_accession: str | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "sample_id": self.sample_id,
            "gene": self.gene,
            "purpose": self.purpose,
            "result": self.result,
            "ncbi_accession": self.ncbi_accession,
            "method": self.method,
            "tested_at": self.tested_at,
            "notes": self.notes,
            "sequence": self.sequence,
            "sequence_header": self.sequence_header,
            "sequence_length": self.sequence_length,
            "primer_forward": self.primer_forward,
            "primer_reverse": self.primer_reverse,
            "blast_top_hit": self.blast_top_hit,
            "blast_identity_pct": self.blast_identity_pct,
            "blast_coverage_pct": self.blast_coverage_pct,
            "blast_hit_accession": self.blast_hit_accession,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class SampleAliquot:
    """Uma alíquota física da cepa (tubo de glicerol, liofilizado, placa...).
    Estoque mutável, CRUD normal — mesmo raciocínio de `SampleTest`: não é
    elo de custódia legal."""

    id: UUID
    organization_id: UUID
    sample_id: UUID
    label: str
    storage_method: str
    freezer: str | None = None
    box: str | None = None
    position: str | None = None
    stored_at: date | None = None
    status: str = "disponivel"
    notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "sample_id": self.sample_id,
            "label": self.label,
            "storage_method": self.storage_method,
            "freezer": self.freezer,
            "box": self.box,
            "position": self.position,
            "stored_at": self.stored_at,
            "status": self.status,
            "notes": self.notes,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
