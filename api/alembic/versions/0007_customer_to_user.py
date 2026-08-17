"""Funde Customer (Pesquisador) em User — pesquisador vira sempre uma conta

Decisão do usuário: parar de tratar "pesquisador"/"cliente" como um contato
solto (customers.name/contact_email, sem login) e passar a exigir que todo
pesquisador seja um organization_member de verdade (conta Google, com
papel). Isso fecha o menu duplicado no front (Pesquisadores vs Usuários) e
elimina o desalinhamento de ter dois cadastros de pessoa que não se falam.

`projects.customer_id` (FK pra customers) vira `projects.customer_user_id`
(FK pra users). Backfill por e-mail: onde `customers.contact_email` bate
com `users.email`, liga automaticamente. Onde não bate (cliente externo sem
conta ainda), o projeto fica sem pesquisador vinculado — precisa convidar a
pessoa (fluxo de invitation do identity) e associar de novo depois.

A tabela `customers` não é apagada nesta migration (só perde o vínculo);
fica como histórico morto até confirmar que o backfill cobriu os casos
reais. Ver ADR novo em docs/decisions/ pra esta decisão.

Revision ID: 0007_customer_to_user
Revises: 0006_project_analyses
"""
from alembic import op

revision = "0007_customer_to_user"
down_revision = "0006_project_analyses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN customer_user_id uuid REFERENCES users(id) ON DELETE SET NULL")

    # Backfill best-effort por e-mail. Só liga quando o e-mail do contato
    # bate com um usuário real da MESMA organização (não entre orgs).
    op.execute(
        """
        UPDATE projects p
           SET customer_user_id = u.id
          FROM customers c
          JOIN organization_members m ON m.organization_id = c.organization_id
          JOIN users u ON u.id = m.user_id AND lower(u.email) = lower(c.contact_email)
         WHERE p.customer_id = c.id
           AND c.contact_email IS NOT NULL
        """
    )

    op.execute("ALTER TABLE projects DROP COLUMN customer_id")
    op.execute("CREATE INDEX idx_projects_customer_user ON projects(customer_user_id)")


def downgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN customer_id uuid REFERENCES customers(id) ON DELETE SET NULL")
    op.execute("DROP INDEX IF EXISTS idx_projects_customer_user")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS customer_user_id")
