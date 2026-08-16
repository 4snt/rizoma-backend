"""Rotas do inventário. Montadas pelo main.py em /api/v2/inventory (tcc-rizoma#9)."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.modules.inventory import service
from app.modules.inventory.schemas import (
    CalibrationDueAlert,
    EquipmentCalibrationCreate,
    EquipmentCalibrationOut,
    EquipmentCreate,
    EquipmentOut,
    EquipmentStatusUpdate,
    ExpiringLotAlert,
    InventoryAlertsOut,
    ReagentConsumptionCreate,
    ReagentConsumptionOut,
    ReagentCreate,
    ReagentLotCreate,
    ReagentLotOut,
    ReagentOut,
)
from app.shared.context import Ctx, get_ctx

router = APIRouter(tags=["inventory"])

CtxDep = Annotated[Ctx, Depends(get_ctx)]


# ── Reagentes ────────────────────────────────────────────────────────────
@router.post("/reagents", response_model=ReagentOut, status_code=status.HTTP_201_CREATED)
async def create_reagent(data: ReagentCreate, ctx: CtxDep) -> ReagentOut:
    return ReagentOut(**vars(await service.create_reagent(ctx, data)))


@router.get("/reagents", response_model=list[ReagentOut])
async def list_reagents(ctx: CtxDep) -> list[ReagentOut]:
    return [ReagentOut(**vars(r)) for r in await service.list_reagents(ctx)]


@router.get("/reagents/{reagent_id}", response_model=ReagentOut)
async def get_reagent(reagent_id: UUID, ctx: CtxDep) -> ReagentOut:
    return ReagentOut(**vars(await service.get_reagent(ctx, reagent_id)))


@router.post(
    "/reagents/{reagent_id}/lots", response_model=ReagentLotOut, status_code=status.HTTP_201_CREATED
)
async def create_lot(reagent_id: UUID, data: ReagentLotCreate, ctx: CtxDep) -> ReagentLotOut:
    return ReagentLotOut(**vars(await service.create_lot(ctx, reagent_id, data)))


@router.get("/reagents/{reagent_id}/lots", response_model=list[ReagentLotOut])
async def list_lots(reagent_id: UUID, ctx: CtxDep) -> list[ReagentLotOut]:
    return [ReagentLotOut(**vars(l)) for l in await service.list_lots(ctx, reagent_id)]


@router.post(
    "/reagent-lots/{lot_id}/consumptions",
    response_model=ReagentConsumptionOut,
    status_code=status.HTTP_201_CREATED,
)
async def consume_lot(lot_id: UUID, data: ReagentConsumptionCreate, ctx: CtxDep) -> ReagentConsumptionOut:
    return ReagentConsumptionOut(**vars(await service.consume_lot(ctx, lot_id, data)))


# ── Equipamentos ─────────────────────────────────────────────────────────
@router.post("/equipment", response_model=EquipmentOut, status_code=status.HTTP_201_CREATED)
async def create_equipment(data: EquipmentCreate, ctx: CtxDep) -> EquipmentOut:
    return EquipmentOut(**vars(await service.create_equipment(ctx, data)))


@router.get("/equipment", response_model=list[EquipmentOut])
async def list_equipment(ctx: CtxDep) -> list[EquipmentOut]:
    return [EquipmentOut(**vars(e)) for e in await service.list_equipment(ctx)]


@router.get("/equipment/{equipment_id}", response_model=EquipmentOut)
async def get_equipment(equipment_id: UUID, ctx: CtxDep) -> EquipmentOut:
    return EquipmentOut(**vars(await service.get_equipment(ctx, equipment_id)))


@router.patch("/equipment/{equipment_id}/status", response_model=EquipmentOut)
async def update_equipment_status(
    equipment_id: UUID, data: EquipmentStatusUpdate, ctx: CtxDep
) -> EquipmentOut:
    return EquipmentOut(**vars(await service.update_equipment_status(ctx, equipment_id, data.status)))


@router.post(
    "/equipment/{equipment_id}/calibrations",
    response_model=EquipmentCalibrationOut,
    status_code=status.HTTP_201_CREATED,
)
async def record_calibration(
    equipment_id: UUID, data: EquipmentCalibrationCreate, ctx: CtxDep
) -> EquipmentCalibrationOut:
    return EquipmentCalibrationOut(**vars(await service.record_calibration(ctx, equipment_id, data)))


@router.get("/equipment/{equipment_id}/calibrations", response_model=list[EquipmentCalibrationOut])
async def list_calibrations(equipment_id: UUID, ctx: CtxDep) -> list[EquipmentCalibrationOut]:
    return [EquipmentCalibrationOut(**vars(c)) for c in await service.list_calibrations(ctx, equipment_id)]


# ── Alertas ──────────────────────────────────────────────────────────────
@router.get("/alerts", response_model=InventoryAlertsOut)
async def get_alerts(
    ctx: CtxDep, within_days: int = Query(default=30, ge=1, le=365)
) -> InventoryAlertsOut:
    data = await service.get_alerts(ctx, within_days)
    return InventoryAlertsOut(
        expiring_lots=[ExpiringLotAlert(**r) for r in data["expiring_lots"]],
        calibrations_due=[CalibrationDueAlert(**r) for r in data["calibrations_due"]],
    )
