"""Regras de negócio do inventário (tcc-rizoma#9).

Não fala SQL — isso é `repository.py`. A única regra de domínio não trivial
aqui é a baixa de reagente: não pode deixar saldo negativo, e precisa apontar
pra alguma coisa rastreável (amostra e/ou job) — senão "baixa de reagente" é
só um número solto, sem serventia pra auditoria ISO 17025.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.modules.inventory.domain.entities import (
    Equipment,
    EquipmentCalibration,
    EquipmentReservation,
    Reagent,
    ReagentConsumption,
    ReagentLot,
)
from app.modules.inventory.repository import PgEquipmentRepository, PgReagentRepository
from app.modules.inventory.schemas import (
    EquipmentCalibrationCreate,
    EquipmentCreate,
    EquipmentReservationCreate,
    ReagentConsumptionCreate,
    ReagentCreate,
    ReagentLotCreate,
)
from app.shared.context import Ctx
from app.shared.ids import new_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Reagentes ────────────────────────────────────────────────────────────
async def create_reagent(ctx: Ctx, data: ReagentCreate) -> Reagent:
    ctx.require("reagent:write")
    repo = PgReagentRepository(ctx.session)
    return await repo.create(
        Reagent(
            id=new_id(), organization_id=ctx.org_id, name=data.name,
            manufacturer=data.manufacturer, catalog_number=data.catalog_number,
            unit=data.unit, created_by=ctx.user_id, created_at=_now(),
        )
    )


async def list_reagents(ctx: Ctx) -> list[Reagent]:
    ctx.require("reagent:read")
    return await PgReagentRepository(ctx.session).list_all()


async def get_reagent(ctx: Ctx, reagent_id: UUID) -> Reagent:
    ctx.require("reagent:read")
    reagent = await PgReagentRepository(ctx.session).get(reagent_id)
    if reagent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reagente não encontrado.")
    return reagent


async def create_lot(ctx: Ctx, reagent_id: UUID, data: ReagentLotCreate) -> ReagentLot:
    ctx.require("reagent:write")
    repo = PgReagentRepository(ctx.session)
    if await repo.get(reagent_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reagente não encontrado.")
    return await repo.create_lot(
        ReagentLot(
            id=new_id(), organization_id=ctx.org_id, reagent_id=reagent_id,
            lot_number=data.lot_number, supplier=data.supplier,
            quantity_received=data.quantity_received, quantity_remaining=data.quantity_received,
            unit=data.unit, received_at=data.received_at or _now(),
            expires_at=data.expires_at, created_by=ctx.user_id, created_at=_now(),
        )
    )


async def list_lots(ctx: Ctx, reagent_id: UUID) -> list[ReagentLot]:
    ctx.require("reagent:read")
    return await PgReagentRepository(ctx.session).list_lots(reagent_id)


async def consume_lot(ctx: Ctx, lot_id: UUID, data: ReagentConsumptionCreate) -> ReagentConsumption:
    """Baixa de reagente. Regra ISO 17025 (tcc-rizoma#9): toda baixa aponta
    pra uma amostra e/ou job — nunca é um número solto sem rastro.
    """
    ctx.require("reagent:write")
    if data.sample_id is None and data.job_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Baixa de reagente precisa referenciar sample_id e/ou job_id — sem isso não é rastreável.",
        )

    repo = PgReagentRepository(ctx.session)
    lot = await repo.get_lot_for_update(lot_id)
    if lot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lote não encontrado.")
    if lot.quantity_remaining < data.quantity:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Saldo insuficiente: restam {lot.quantity_remaining} {lot.unit}, "
            f"pedida baixa de {data.quantity}.",
        )

    await repo.debit_lot(lot_id, data.quantity)
    try:
        return await repo.record_consumption(
            ReagentConsumption(
                id=new_id(), organization_id=ctx.org_id, reagent_lot_id=lot_id,
                sample_id=data.sample_id, job_id=data.job_id, quantity=data.quantity,
                consumed_by=ctx.user_id, consumed_at=_now(), notes=data.notes,
            )
        )
    except IntegrityError as exc:
        # sample_id/job_id apontando pra algo que não existe — FK violation crua
        # vira 404 de domínio, não 500. O débito do lote já rodou nesta mesma
        # transação; o rollback do Ctx (shared/context.py) desfaz tudo junto.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "sample_id ou job_id referenciado não existe."
        ) from exc


# ── Equipamentos ─────────────────────────────────────────────────────────
async def create_equipment(ctx: Ctx, data: EquipmentCreate) -> Equipment:
    ctx.require("equipment:write")
    repo = PgEquipmentRepository(ctx.session)
    return await repo.create(
        Equipment(
            id=new_id(), organization_id=ctx.org_id, name=data.name,
            identifier=data.identifier, manufacturer=data.manufacturer, model=data.model,
            serial_number=data.serial_number, location=data.location, status="active",
            created_by=ctx.user_id, created_at=_now(),
        )
    )


async def list_equipment(ctx: Ctx) -> list[Equipment]:
    ctx.require("equipment:read")
    return await PgEquipmentRepository(ctx.session).list_all()


async def get_equipment(ctx: Ctx, equipment_id: UUID) -> Equipment:
    ctx.require("equipment:read")
    equipment = await PgEquipmentRepository(ctx.session).get(equipment_id)
    if equipment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Equipamento não encontrado.")
    return equipment


async def update_equipment_status(ctx: Ctx, equipment_id: UUID, status_: str) -> Equipment:
    ctx.require("equipment:write")
    equipment = await PgEquipmentRepository(ctx.session).update_status(equipment_id, status_)
    if equipment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Equipamento não encontrado.")
    return equipment


async def record_calibration(
    ctx: Ctx, equipment_id: UUID, data: EquipmentCalibrationCreate
) -> EquipmentCalibration:
    ctx.require("equipment:write")
    repo = PgEquipmentRepository(ctx.session)
    if await repo.get(equipment_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Equipamento não encontrado.")
    return await repo.record_calibration(
        EquipmentCalibration(
            id=new_id(), organization_id=ctx.org_id, equipment_id=equipment_id,
            calibrated_at=data.calibrated_at, next_calibration_due=data.next_calibration_due,
            certificate_number=data.certificate_number, performed_by=data.performed_by,
            notes=data.notes, created_by=ctx.user_id, created_at=_now(),
        )
    )


async def list_calibrations(ctx: Ctx, equipment_id: UUID) -> list[EquipmentCalibration]:
    ctx.require("equipment:read")
    return await PgEquipmentRepository(ctx.session).list_calibrations(equipment_id)


async def create_reservation(
    ctx: Ctx, equipment_id: UUID, data: EquipmentReservationCreate
) -> EquipmentReservation:
    ctx.require("equipment:write")
    if data.ends_at <= data.starts_at:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "ends_at precisa ser depois de starts_at."
        )
    repo = PgEquipmentRepository(ctx.session)
    if await repo.get(equipment_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Equipamento não encontrado.")
    if await repo.has_overlapping_reservation(equipment_id, data.starts_at, data.ends_at):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Equipamento já reservado nesse período."
        )
    return await repo.create_reservation(
        EquipmentReservation(
            id=new_id(), organization_id=ctx.org_id, equipment_id=equipment_id,
            project_id=data.project_id, starts_at=data.starts_at, ends_at=data.ends_at,
            status="confirmed", notes=data.notes, reserved_by=ctx.user_id, created_at=_now(),
        )
    )


async def list_reservations(ctx: Ctx, equipment_id: UUID) -> list[EquipmentReservation]:
    ctx.require("equipment:read")
    return await PgEquipmentRepository(ctx.session).list_reservations(equipment_id)


async def cancel_reservation(
    ctx: Ctx, equipment_id: UUID, reservation_id: UUID
) -> EquipmentReservation:
    ctx.require("equipment:write")
    reservation = await PgEquipmentRepository(ctx.session).cancel_reservation(
        equipment_id, reservation_id
    )
    if reservation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reserva não encontrada ou já cancelada.")
    return reservation


# ── Alertas ──────────────────────────────────────────────────────────────
async def get_alerts(ctx: Ctx, within_days: int) -> dict[str, list[dict[str, Any]]]:
    ctx.require("reagent:read")
    ctx.require("equipment:read")
    reagent_repo = PgReagentRepository(ctx.session)
    equipment_repo = PgEquipmentRepository(ctx.session)
    return {
        "expiring_lots": await reagent_repo.expiring_lots(within_days),
        "calibrations_due": await equipment_repo.calibrations_due(within_days),
    }
