"""Remove a coluna `strain_name` de `samples`

Redundante com o código LIMS da amostra (`code`), que já é o identificador
fixo pós-registro. Nome de linhagem sai do formulário de registro e do
schema.

Isto APAGA os valores já preenchidos (inclusive os importados pelo script
NEBIM). O downgrade recria a coluna vazia; os valores não voltam.

Revision ID: 0012_drop_strain_name
Revises: 0011_isolate_registry
"""
from alembic import op

revision = "0012_drop_strain_name"
down_revision = "0011_isolate_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE samples DROP COLUMN IF EXISTS strain_name")


def downgrade() -> None:
    op.execute("ALTER TABLE samples ADD COLUMN strain_name text")
