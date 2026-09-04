"""Contratos do módulo de inventário — reagentes e equipamentos (tcc-rizoma#9)."""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

EQUIPMENT_STATUSES = ("active", "maintenance", "retired")


# ── Reagentes ────────────────────────────────────────────────────────────
class ReagentCreate(BaseModel):
    name: str = Field(min_length=1)
    manufacturer: str | None = None
    catalog_number: str | None = None
    unit: str = Field(min_length=1)


class ReagentOut(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    manufacturer: str | None
    catalog_number: str | None
    unit: str
    created_by: UUID | None
    created_at: datetime


class ReagentLotCreate(BaseModel):
    lot_number: str = Field(min_length=1)
    supplier: str | None = None
    quantity_received: Decimal = Field(gt=0)
    unit: str = Field(min_length=1)
    received_at: datetime | None = None
    expires_at: date | None = None


class ReagentLotOut(BaseModel):
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


class ReagentConsumptionCreate(BaseModel):
    """Baixa de reagente — vincula o consumo a uma amostra e/ou a um job.

    Pelo menos um de `sample_id`/`job_id` deveria estar presente pra a baixa
    servir de rastreabilidade real; o service valida isso (não é regra de
    schema — 400 de domínio, não 422 genérico, mesma convenção do módulo
    `laboratory`).
    """
    sample_id: UUID | None = None
    job_id: UUID | None = None
    quantity: Decimal = Field(gt=0)
    notes: str | None = None


class ReagentConsumptionOut(BaseModel):
    id: UUID
    organization_id: UUID
    reagent_lot_id: UUID
    sample_id: UUID | None
    job_id: UUID | None
    quantity: Decimal
    consumed_by: UUID | None
    consumed_at: datetime
    notes: str | None


# ── Equipamentos ─────────────────────────────────────────────────────────
class EquipmentCreate(BaseModel):
    name: str = Field(min_length=1)
    identifier: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    location: str | None = None


class EquipmentStatusUpdate(BaseModel):
    status: str = Field(pattern="^(active|maintenance|retired)$")


class EquipmentOut(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    identifier: str | None
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    location: str | None
    status: str
    created_by: UUID | None
    created_at: datetime


class EquipmentCalibrationCreate(BaseModel):
    calibrated_at: datetime
    next_calibration_due: date
    certificate_number: str | None = None
    performed_by: str | None = None
    notes: str | None = None


class EquipmentCalibrationOut(BaseModel):
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


class EquipmentReservationCreate(BaseModel):
    starts_at: datetime
    ends_at: datetime
    project_id: UUID | None = None
    notes: str | None = None


class EquipmentReservationOut(BaseModel):
    id: UUID
    organization_id: UUID
    equipment_id: UUID
    project_id: UUID | None
    starts_at: datetime
    ends_at: datetime
    status: str
    notes: str | None
    reserved_by: UUID | None
    created_at: datetime


# ── Alertas ──────────────────────────────────────────────────────────────
class ExpiringLotAlert(BaseModel):
    reagent_lot_id: UUID
    reagent_id: UUID
    reagent_name: str
    lot_number: str
    expires_at: date
    days_remaining: int


class CalibrationDueAlert(BaseModel):
    equipment_id: UUID
    equipment_name: str
    last_calibration_id: UUID
    next_calibration_due: date
    days_remaining: int


class InventoryAlertsOut(BaseModel):
    expiring_lots: list[ExpiringLotAlert]
    calibrations_due: list[CalibrationDueAlert]
