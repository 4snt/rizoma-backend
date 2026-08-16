"""Inventário: reagentes (lote/validade/baixa) + equipamentos (calibração)

tcc-rizoma#9 — funções padrão de LIMS que reforçam conformidade ISO/IEC 17025
e ainda não existiam no Rizoma (confirmado por grep: zero código antes desta
migration). Tabelas com escopo de organização, RLS igual ao resto do baseline.

Revision ID: 0004_inventory
Revises: 0003_job_status_notify
"""
from alembic import op

revision = "0004_inventory"
down_revision = "0003_job_status_notify"
branch_labels = None
depends_on = None

TABLES = [
    "reagents",
    "reagent_lots",
    "reagent_consumptions",
    "equipment",
    "equipment_calibrations",
]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE reagents (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name            text NOT NULL,
            manufacturer    text,
            catalog_number  text,
            unit            text NOT NULL,
            created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_reagents_org ON reagents(organization_id);

        CREATE TABLE reagent_lots (
            id                 uuid PRIMARY KEY,
            organization_id    uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            reagent_id         uuid NOT NULL REFERENCES reagents(id) ON DELETE CASCADE,
            lot_number         text NOT NULL,
            supplier           text,
            quantity_received  numeric NOT NULL CHECK (quantity_received > 0),
            quantity_remaining numeric NOT NULL CHECK (quantity_remaining >= 0),
            unit               text NOT NULL,
            received_at        timestamptz NOT NULL DEFAULT now(),
            expires_at         date,
            created_by         uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at         timestamptz NOT NULL DEFAULT now(),
            UNIQUE (reagent_id, lot_number)
        );
        CREATE INDEX idx_reagent_lots_org ON reagent_lots(organization_id);
        CREATE INDEX idx_reagent_lots_expires ON reagent_lots(expires_at) WHERE expires_at IS NOT NULL;

        CREATE TABLE reagent_consumptions (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            reagent_lot_id  uuid NOT NULL REFERENCES reagent_lots(id) ON DELETE CASCADE,
            sample_id       uuid REFERENCES samples(id) ON DELETE SET NULL,
            job_id          uuid REFERENCES pipeline_jobs(id) ON DELETE SET NULL,
            quantity        numeric NOT NULL CHECK (quantity > 0),
            consumed_by     uuid REFERENCES users(id) ON DELETE SET NULL,
            consumed_at     timestamptz NOT NULL DEFAULT now(),
            notes           text,
            CHECK (sample_id IS NOT NULL OR job_id IS NOT NULL)
        );
        CREATE INDEX idx_reagent_consumptions_org ON reagent_consumptions(organization_id);
        CREATE INDEX idx_reagent_consumptions_lot ON reagent_consumptions(reagent_lot_id);

        CREATE TABLE equipment (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name            text NOT NULL,
            identifier      text,
            manufacturer    text,
            model           text,
            serial_number   text,
            location        text,
            status          text NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'maintenance', 'retired')),
            created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_equipment_org ON equipment(organization_id);

        CREATE TABLE equipment_calibrations (
            id                    uuid PRIMARY KEY,
            organization_id       uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            equipment_id          uuid NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
            calibrated_at         timestamptz NOT NULL,
            next_calibration_due  date NOT NULL,
            certificate_number    text,
            performed_by          text,
            notes                 text,
            created_by            uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at            timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_equipment_calibrations_org ON equipment_calibrations(organization_id);
        CREATE INDEX idx_equipment_calibrations_equip ON equipment_calibrations(equipment_id, calibrated_at DESC);
        """
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                organization_id = NULLIF(current_setting('rizoma.current_org', true), '')::uuid
            )
            WITH CHECK (
                organization_id = NULLIF(current_setting('rizoma.current_org', true), '')::uuid
            )
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS equipment_calibrations")
    op.execute("DROP TABLE IF EXISTS equipment")
    op.execute("DROP TABLE IF EXISTS reagent_consumptions")
    op.execute("DROP TABLE IF EXISTS reagent_lots")
    op.execute("DROP TABLE IF EXISTS reagents")
