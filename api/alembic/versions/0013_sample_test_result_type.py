"""Adiciona result_type/result_value/result_unit em sample_tests

Separa testes bioquímicos qualitativos (enzimáticos padrão, resultado
+/-/++/-+/N em `result`) dos quantitativos (quando dá pra medir de
verdade — `result_value` numérico + `result_unit`). Sem enum/CHECK no
banco: mesmo catálogo aberto do `test_name`, front decide o rótulo.

Revision ID: 0013_sample_test_result_type
Revises: 0012_drop_strain_name
"""
from alembic import op

revision = "0013_sample_test_result_type"
down_revision = "0012_drop_strain_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE sample_tests
            ADD COLUMN result_type text,
            ADD COLUMN result_value numeric,
            ADD COLUMN result_unit text
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE sample_tests
            DROP COLUMN IF EXISTS result_type,
            DROP COLUMN IF EXISTS result_value,
            DROP COLUMN IF EXISTS result_unit
        """
    )
