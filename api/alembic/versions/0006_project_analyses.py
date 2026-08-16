"""Coluna analyses em projects — catálogo de análise escolhido na criação

Antes só existia em app/api/v1 (código morto, nunca montado). O frontend
(admin/projects/new e metagenomics/page.tsx) sempre mandou esse campo na
criação de projeto, mas v2/lims.ProjectCreate não tinha onde guardar —
Pydantic ignorava o campo desconhecido em silêncio (ver
bio-frontend/lib/api.ts, comentário em createProject, e
4snt/rizoma-backend#10).

Revision ID: 0006_project_analyses
Revises: 0005_webhooks
"""
from alembic import op

revision = "0006_project_analyses"
down_revision = "0005_webhooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE projects ADD COLUMN analyses jsonb NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS analyses")
