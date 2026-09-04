"""Persistência do inventário. SQL cru aqui, igual ao `lims` — a sessão já
chega com o GUC de tenant setado pelo `Ctx` (ver `shared/context.py`), então
RLS isola por organização sem precisar repetir `WHERE organization_id = ...`
em todo SELECT (mas os `WHERE` continuam explícitos onde o índice pede).
"""
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.domain.entities import (
    Equipment,
    EquipmentCalibration,
    EquipmentReservation,
    Reagent,
    ReagentConsumption,
    ReagentLot,
)

_REAGENT_COLS = "id, organization_id, name, manufacturer, catalog_number, unit, created_by, created_at"
_LOT_COLS = (
    "id, organization_id, reagent_id, lot_number, supplier, quantity_received, "
    "quantity_remaining, unit, received_at, expires_at, created_by, created_at"
)
_CONSUMPTION_COLS = (
    "id, organization_id, reagent_lot_id, sample_id, job_id, quantity, "
    "consumed_by, consumed_at, notes"
)
_EQUIPMENT_COLS = (
    "id, organization_id, name, identifier, manufacturer, model, serial_number, "
    "location, status, created_by, created_at"
)
_CALIBRATION_COLS = (
    "id, organization_id, equipment_id, calibrated_at, next_calibration_due, "
    "certificate_number, performed_by, notes, created_by, created_at"
)
_RESERVATION_COLS = (
    "id, organization_id, equipment_id, project_id, starts_at, ends_at, "
    "status, notes, reserved_by, created_at"
)


class PgReagentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, r: Reagent) -> Reagent:
        row = (
            await self._s.execute(
                text(
                    f"INSERT INTO reagents ({_REAGENT_COLS}) "
                    "VALUES (:id, :org, :name, :manufacturer, :catalog_number, :unit, :created_by, :created_at) "
                    f"RETURNING {_REAGENT_COLS}"
                ),
                {
                    "id": str(r.id), "org": str(r.organization_id), "name": r.name,
                    "manufacturer": r.manufacturer, "catalog_number": r.catalog_number,
                    "unit": r.unit, "created_by": str(r.created_by) if r.created_by else None,
                    "created_at": r.created_at,
                },
            )
        ).mappings().one()
        return Reagent(**dict(row))

    async def list_all(self) -> list[Reagent]:
        rows = (await self._s.execute(text(f"SELECT {_REAGENT_COLS} FROM reagents ORDER BY name"))).mappings().all()
        return [Reagent(**dict(r)) for r in rows]

    async def get(self, reagent_id: UUID) -> Reagent | None:
        row = (
            await self._s.execute(
                text(f"SELECT {_REAGENT_COLS} FROM reagents WHERE id = :id"), {"id": str(reagent_id)}
            )
        ).mappings().first()
        return Reagent(**dict(row)) if row else None

    async def create_lot(self, lot: ReagentLot) -> ReagentLot:
        row = (
            await self._s.execute(
                text(
                    f"INSERT INTO reagent_lots ({_LOT_COLS}) "
                    "VALUES (:id, :org, :reagent_id, :lot_number, :supplier, :qty_recv, "
                    ":qty_rem, :unit, :received_at, :expires_at, :created_by, :created_at) "
                    f"RETURNING {_LOT_COLS}"
                ),
                {
                    "id": str(lot.id), "org": str(lot.organization_id), "reagent_id": str(lot.reagent_id),
                    "lot_number": lot.lot_number, "supplier": lot.supplier,
                    "qty_recv": lot.quantity_received, "qty_rem": lot.quantity_remaining,
                    "unit": lot.unit, "received_at": lot.received_at, "expires_at": lot.expires_at,
                    "created_by": str(lot.created_by) if lot.created_by else None,
                    "created_at": lot.created_at,
                },
            )
        ).mappings().one()
        return ReagentLot(**dict(row))

    async def list_lots(self, reagent_id: UUID) -> list[ReagentLot]:
        rows = (
            await self._s.execute(
                text(f"SELECT {_LOT_COLS} FROM reagent_lots WHERE reagent_id = :r ORDER BY expires_at NULLS LAST"),
                {"r": str(reagent_id)},
            )
        ).mappings().all()
        return [ReagentLot(**dict(r)) for r in rows]

    async def get_lot_for_update(self, lot_id: UUID) -> ReagentLot | None:
        row = (
            await self._s.execute(
                text(f"SELECT {_LOT_COLS} FROM reagent_lots WHERE id = :id FOR UPDATE"), {"id": str(lot_id)}
            )
        ).mappings().first()
        return ReagentLot(**dict(row)) if row else None

    async def debit_lot(self, lot_id: UUID, quantity: Any) -> None:
        await self._s.execute(
            text("UPDATE reagent_lots SET quantity_remaining = quantity_remaining - :q WHERE id = :id"),
            {"q": quantity, "id": str(lot_id)},
        )

    async def record_consumption(self, c: ReagentConsumption) -> ReagentConsumption:
        row = (
            await self._s.execute(
                text(
                    f"INSERT INTO reagent_consumptions ({_CONSUMPTION_COLS}) "
                    "VALUES (:id, :org, :lot_id, :sample_id, :job_id, :quantity, :consumed_by, :consumed_at, :notes) "
                    f"RETURNING {_CONSUMPTION_COLS}"
                ),
                {
                    "id": str(c.id), "org": str(c.organization_id), "lot_id": str(c.reagent_lot_id),
                    "sample_id": str(c.sample_id) if c.sample_id else None,
                    "job_id": str(c.job_id) if c.job_id else None,
                    "quantity": c.quantity,
                    "consumed_by": str(c.consumed_by) if c.consumed_by else None,
                    "consumed_at": c.consumed_at, "notes": c.notes,
                },
            )
        ).mappings().one()
        return ReagentConsumption(**dict(row))

    async def expiring_lots(self, within_days: int) -> list[dict[str, Any]]:
        rows = (
            await self._s.execute(
                text(
                    "SELECT l.id AS reagent_lot_id, l.reagent_id, r.name AS reagent_name, "
                    "l.lot_number, l.expires_at, "
                    "(l.expires_at - CURRENT_DATE) AS days_remaining "
                    "FROM reagent_lots l JOIN reagents r ON r.id = l.reagent_id "
                    "WHERE l.expires_at IS NOT NULL "
                    "  AND l.expires_at <= CURRENT_DATE + make_interval(days => :d) "
                    "  AND l.quantity_remaining > 0 "
                    "ORDER BY l.expires_at"
                ),
                {"d": within_days},
            )
        ).mappings().all()
        return [dict(r) for r in rows]


class PgEquipmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, e: Equipment) -> Equipment:
        row = (
            await self._s.execute(
                text(
                    f"INSERT INTO equipment ({_EQUIPMENT_COLS}) "
                    "VALUES (:id, :org, :name, :identifier, :manufacturer, :model, :serial_number, "
                    ":location, :status, :created_by, :created_at) "
                    f"RETURNING {_EQUIPMENT_COLS}"
                ),
                {
                    "id": str(e.id), "org": str(e.organization_id), "name": e.name,
                    "identifier": e.identifier, "manufacturer": e.manufacturer, "model": e.model,
                    "serial_number": e.serial_number, "location": e.location, "status": e.status,
                    "created_by": str(e.created_by) if e.created_by else None, "created_at": e.created_at,
                },
            )
        ).mappings().one()
        return Equipment(**dict(row))

    async def list_all(self) -> list[Equipment]:
        rows = (await self._s.execute(text(f"SELECT {_EQUIPMENT_COLS} FROM equipment ORDER BY name"))).mappings().all()
        return [Equipment(**dict(r)) for r in rows]

    async def get(self, equipment_id: UUID) -> Equipment | None:
        row = (
            await self._s.execute(
                text(f"SELECT {_EQUIPMENT_COLS} FROM equipment WHERE id = :id"), {"id": str(equipment_id)}
            )
        ).mappings().first()
        return Equipment(**dict(row)) if row else None

    async def update_status(self, equipment_id: UUID, status_: str) -> Equipment | None:
        row = (
            await self._s.execute(
                text(f"UPDATE equipment SET status = :s WHERE id = :id RETURNING {_EQUIPMENT_COLS}"),
                {"s": status_, "id": str(equipment_id)},
            )
        ).mappings().first()
        return Equipment(**dict(row)) if row else None

    async def record_calibration(self, c: EquipmentCalibration) -> EquipmentCalibration:
        row = (
            await self._s.execute(
                text(
                    f"INSERT INTO equipment_calibrations ({_CALIBRATION_COLS}) "
                    "VALUES (:id, :org, :equipment_id, :calibrated_at, :next_due, "
                    ":cert, :performed_by, :notes, :created_by, :created_at) "
                    f"RETURNING {_CALIBRATION_COLS}"
                ),
                {
                    "id": str(c.id), "org": str(c.organization_id), "equipment_id": str(c.equipment_id),
                    "calibrated_at": c.calibrated_at, "next_due": c.next_calibration_due,
                    "cert": c.certificate_number, "performed_by": c.performed_by, "notes": c.notes,
                    "created_by": str(c.created_by) if c.created_by else None, "created_at": c.created_at,
                },
            )
        ).mappings().one()
        return EquipmentCalibration(**dict(row))

    async def list_calibrations(self, equipment_id: UUID) -> list[EquipmentCalibration]:
        rows = (
            await self._s.execute(
                text(
                    f"SELECT {_CALIBRATION_COLS} FROM equipment_calibrations "
                    "WHERE equipment_id = :e ORDER BY calibrated_at DESC"
                ),
                {"e": str(equipment_id)},
            )
        ).mappings().all()
        return [EquipmentCalibration(**dict(r)) for r in rows]

    async def calibrations_due(self, within_days: int) -> list[dict[str, Any]]:
        # Última calibração de cada equipamento (DISTINCT ON), e só entra no
        # alerta se o equipamento ainda estiver ativo.
        rows = (
            await self._s.execute(
                text(
                    "SELECT DISTINCT ON (c.equipment_id) "
                    "  c.equipment_id, eq.name AS equipment_name, c.id AS last_calibration_id, "
                    "  c.next_calibration_due, "
                    "  (c.next_calibration_due - CURRENT_DATE) AS days_remaining "
                    "FROM equipment_calibrations c "
                    "JOIN equipment eq ON eq.id = c.equipment_id AND eq.status = 'active' "
                    "ORDER BY c.equipment_id, c.calibrated_at DESC"
                )
            )
        ).mappings().all()
        due = [
            dict(r) for r in rows
            if r["next_calibration_due"] is not None
            and r["days_remaining"] is not None
            and r["days_remaining"] <= within_days
        ]
        return due

    async def create_reservation(self, r: EquipmentReservation) -> EquipmentReservation:
        row = (
            await self._s.execute(
                text(
                    f"INSERT INTO equipment_reservations ({_RESERVATION_COLS}) "
                    "VALUES (:id, :org, :equipment_id, :project_id, :starts_at, :ends_at, "
                    ":status, :notes, :reserved_by, :created_at) "
                    f"RETURNING {_RESERVATION_COLS}"
                ),
                {
                    "id": str(r.id), "org": str(r.organization_id), "equipment_id": str(r.equipment_id),
                    "project_id": str(r.project_id) if r.project_id else None,
                    "starts_at": r.starts_at, "ends_at": r.ends_at, "status": r.status,
                    "notes": r.notes, "reserved_by": str(r.reserved_by) if r.reserved_by else None,
                    "created_at": r.created_at,
                },
            )
        ).mappings().one()
        return EquipmentReservation(**dict(row))

    async def list_reservations(self, equipment_id: UUID) -> list[EquipmentReservation]:
        rows = (
            await self._s.execute(
                text(
                    f"SELECT {_RESERVATION_COLS} FROM equipment_reservations "
                    "WHERE equipment_id = :e ORDER BY starts_at"
                ),
                {"e": str(equipment_id)},
            )
        ).mappings().all()
        return [EquipmentReservation(**dict(r)) for r in rows]

    async def has_overlapping_reservation(
        self, equipment_id: UUID, starts_at: Any, ends_at: Any
    ) -> bool:
        row = (
            await self._s.execute(
                text(
                    "SELECT 1 FROM equipment_reservations "
                    "WHERE equipment_id = :e AND status = 'confirmed' "
                    "  AND starts_at < :new_ends_at AND ends_at > :new_starts_at "
                    "LIMIT 1"
                ),
                {"e": str(equipment_id), "new_starts_at": starts_at, "new_ends_at": ends_at},
            )
        ).first()
        return row is not None

    async def cancel_reservation(
        self, equipment_id: UUID, reservation_id: UUID
    ) -> EquipmentReservation | None:
        """`AND equipment_id = :eq` de propósito: o id da reserva sozinho não
        prova que ela pertence ao equipamento da URL."""
        row = (
            await self._s.execute(
                text(
                    "UPDATE equipment_reservations SET status = 'cancelled' "
                    "WHERE id = :id AND equipment_id = :eq AND status = 'confirmed' "
                    f"RETURNING {_RESERVATION_COLS}"
                ),
                {"id": str(reservation_id), "eq": str(equipment_id)},
            )
        ).mappings().first()
        return EquipmentReservation(**dict(row)) if row else None
