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
from datetime import datetime
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
        }
