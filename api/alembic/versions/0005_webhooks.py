"""Assinaturas de webhook — tcc-rizoma#10 (interoperabilidade)

Uma organização assina um ou mais event_types (ex: 'job.completed',
'job.failed', 'sample.created') e recebe POST com o payload assinado
(HMAC-SHA256 do corpo, header X-Rizoma-Signature) sempre que o evento
acontece. Dispatch é best-effort (não bloqueia o fluxo que gerou o evento) —
ver app/modules/interop/service.py.

Revision ID: 0005_webhooks
Revises: 0004_inventory
"""
from alembic import op

revision = "0005_webhooks"
down_revision = "0004_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE webhook_subscriptions (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            url             text NOT NULL,
            event_types     text[] NOT NULL,
            secret          text NOT NULL,
            is_active       boolean NOT NULL DEFAULT true,
            created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_webhook_subscriptions_org ON webhook_subscriptions(organization_id);
        """
    )
    op.execute("ALTER TABLE webhook_subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE webhook_subscriptions FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON webhook_subscriptions
        USING (
            organization_id = NULLIF(current_setting('rizoma.current_org', true), '')::uuid
        )
        WITH CHECK (
            organization_id = NULLIF(current_setting('rizoma.current_org', true), '')::uuid
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS webhook_subscriptions")
