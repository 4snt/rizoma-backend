"""Entidades do módulo de inventário (reagentes + equipamentos) — tcc-rizoma#9.

Existe pra cobrir a lacuna de ISO/IEC 17025 que o Rizoma ainda não tinha:
rastreabilidade de reagente (lote/validade/baixa) e de equipamento
(calibração). Deliberadamente fora do módulo `laboratory` (que é sobre
*resultado* de análise) — inventário é sobre os insumos que produzem o
resultado, ciclo de vida diferente.
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class Reagent:
    id: UUID
    organization_id: UUID
    name: str
    manufacturer: str | None
    catalog_number: str | None
    unit: str
    created_by: UUID | None
    created_at: datetime


@dataclass(frozen=True)
class ReagentLot:
    id: UUID
    organization_id: UUID
    reagent_id: UUID
    lot_number: str
    supplier: str | None
    quantity_received: Decimal
    quantity_remaining: Decimal
    unit: str
    received_at: datetime
    expires_at: date | None
    created_by: UUID | None
    created_at: datetime


@dataclass(frozen=True)
class ReagentConsumption:
    id: UUID
    organization_id: UUID
    reagent_lot_id: UUID
    sample_id: UUID | None
    job_id: UUID | None
    quantity: Decimal
    consumed_by: UUID | None
    consumed_at: datetime
    notes: str | None


@dataclass(frozen=True)
class Equipment:
    id: UUID
    organization_id: UUID
    name: str
    identifier: str | None
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    location: str | None
    status: str  # 'active' | 'maintenance' | 'retired'
    created_by: UUID | None
    created_at: datetime


@dataclass(frozen=True)
class EquipmentCalibration:
    id: UUID
    organization_id: UUID
    equipment_id: UUID
    calibrated_at: datetime
    next_calibration_due: date
    certificate_number: str | None
    performed_by: str | None
    notes: str | None
    created_by: UUID | None
    created_at: datetime
