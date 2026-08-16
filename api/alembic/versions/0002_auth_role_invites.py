"""Auth: role em users + tabela invited_users

O fluxo de login Google (app/api/v1/auth.py, app/api/v1/admin.py) referencia
`users.role` e a tabela `invited_users`, mas o baseline (0001) nunca criou nem
um nem outro — só existe `organization_members.role` (por organização) e
`invitations` (escopada a organização, colunas diferentes). Resultado: todo
INSERT/SELECT do login real batia em UndefinedColumn/UndefinedTable.

Este é o modelo global simples descrito em docs/LOGIN_GUIDE.md (researcher /
admin), independente do multi-tenant por organização — mantido separado de
propósito, ver issue 4snt/rizoma-backend#1.

Revision ID: 0002_auth_role_invites
Revises: 0001_mvp_baseline
"""
from alembic import op

revision = "0002_auth_role_invites"
down_revision = "0001_mvp_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN role text NOT NULL DEFAULT 'researcher'
                CHECK (role IN ('researcher', 'admin'));
        """
    )

    op.execute(
        """
        CREATE TABLE invited_users (
            id          uuid PRIMARY KEY,
            email       text NOT NULL UNIQUE,
            role        text NOT NULL DEFAULT 'researcher'
                        CHECK (role IN ('researcher', 'admin')),
            invited_by  uuid REFERENCES users(id) ON DELETE SET NULL,
            invited_at  timestamptz NOT NULL DEFAULT now(),
            used_at     timestamptz
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE invited_users")
    op.execute("ALTER TABLE users DROP COLUMN role")
