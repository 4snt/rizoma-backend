"""Agenda de uso de equipamento (reserva)

tcc-rizoma#9 — equipamento de laboratório é recurso compartilhado entre
pesquisadores; sem agenda, dois grupos marcam o mesmo horário no mesmo
equipamento e só descobrem o choque na hora de usar. Tabela nova, RLS igual
ao resto do módulo `inventory`.

Revision ID: 0014_equipment_reservations
Revises: 0013_sample_test_result_type
"""
from alembic import op

revision = "0014_equipment_reservations"
down_revision = "0013_sample_test_result_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE equipment_reservations (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            equipment_id    uuid NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
            project_id      uuid REFERENCES projects(id) ON DELETE SET NULL,
            starts_at       timestamptz NOT NULL,
            ends_at         timestamptz NOT NULL,
            status          text NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled')),
            notes           text,
            reserved_by     uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            CHECK (ends_at > starts_at)
        );
        CREATE INDEX idx_equipment_reservations_org ON equipment_reservations(organization_id);
        CREATE INDEX idx_equipment_reservations_equip ON equipment_reservations(equipment_id, starts_at);
        """
    )

    op.execute("ALTER TABLE equipment_reservations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE equipment_reservations FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON equipment_reservations
        USING (
            organization_id = NULLIF(current_setting('rizoma.current_org', true), '')::uuid
        )
        WITH CHECK (
            organization_id = NULLIF(current_setting('rizoma.current_org', true), '')::uuid
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS equipment_reservations")
