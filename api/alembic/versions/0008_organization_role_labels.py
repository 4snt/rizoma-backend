"""Rótulo de papel customizável por organização

Papel técnico (org_admin, coordinator, tech_responsible, field_tech,
lab_tech, bioinformatician, client, viewer) continua fixo — é o que decide
permissão de verdade (app/shared/context.py::PERMISSIONS), não muda.

O que muda por laboratório é como cada papel É CHAMADO na tela: um
laboratório organiza por titulação (Graduando/Mestrando/Doutorando), outro
por função (Estagiário/Técnico/Pesquisador), e o Rizoma não pode embutir
vocabulário de um lab específico no código.

`organizations.role_labels` é um JSONB array: cada item é
`{"label": "...", "role": "..."}`. `role` é sempre um dos 8 papéis técnicos
válidos, sem exceção. Vários rótulos podem apontar pro mesmo papel — não é
um mapa 1:1 papel->rótulo, porque um laboratório pode querer diferenciar,
por exemplo, "Mestrando" e "Doutorando" mesmo os dois sendo tecnicamente
`lab_tech`. Papel sem nenhuma entrada cai no rótulo padrão (dicionário fixo
no frontend) — a organização só sobrescreve o que quiser.

Revision ID: 0008_organization_role_labels
Revises: 0007_customer_to_user
"""
from alembic import op

revision = "0008_organization_role_labels"
down_revision = "0007_customer_to_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE organizations "
        "ADD COLUMN role_labels jsonb NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS role_labels")
