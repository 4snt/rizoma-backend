"""Estende `samples` com dados biológicos (bactérias/fungos): tipo de
organismo, morfologia de colônia (padrão Bergey), e duas tabelas filhas
mutáveis para testes bioquímicos/enzimáticos (catálogo aberto) e genes
sequenciados (metadado + resultado, sem sequência bruta/FASTA).

Colunas de morfologia com CHECK fechado (não JSONB): o vocabulário Bergey é
estável e os campos precisam ser filtráveis/consultáveis individualmente,
mesmo raciocínio de `matrix`/`status` no baseline — não o de `dada2_params`,
cujo shape é decidido por um pipeline externo.

`sample_tests`/`sample_genes` são resultado de bancada, não elo de custódia
legal (`custody_events`, append-only) nem resultado formal ISO 17025
(`lab_results`/`result_versions`, módulo `laboratory`) — por isso são CRUD
normal, sem trigger de imutabilidade.

Revision ID: 0010_sample_biological_data
Revises: 0009_drop_metagenomics_columns
"""
from alembic import op

revision = "0010_sample_biological_data"
down_revision = "0009_drop_metagenomics_columns"
branch_labels = None
depends_on = None

TABLES = ["sample_tests", "sample_genes"]


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE samples
            ADD COLUMN organism_type text CHECK (organism_type IN ('bacteria','fungo','outro')),
            ADD COLUMN colonia_forma text CHECK (colonia_forma IN
                ('circular','irregular','filamentosa','rizoide','fusiforme','puntiforme')),
            ADD COLUMN colonia_elevacao text CHECK (colonia_elevacao IN
                ('plana','elevada','convexa','pulvinada','umbonada','crateriforme')),
            ADD COLUMN colonia_margem text CHECK (colonia_margem IN
                ('inteira','ondulada','lobada','filiforme','crespa')),
            ADD COLUMN colonia_cor text,
            ADD COLUMN colonia_textura text CHECK (colonia_textura IN
                ('lisa','rugosa','mucoide','seca','granular','viscosa')),
            ADD COLUMN colonia_tamanho_mm numeric,
            ADD COLUMN colonia_opacidade text CHECK (colonia_opacidade IN
                ('opaca','translucida','transparente'));
        """
    )

    op.execute(
        """
        CREATE TABLE sample_tests (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            sample_id       uuid NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
            test_name       text NOT NULL,
            result          text,
            method          text,
            tested_at       date,
            notes           text,
            created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            UNIQUE (sample_id, test_name, tested_at)
        );
        CREATE INDEX idx_sample_tests_sample ON sample_tests(sample_id);
        CREATE INDEX idx_sample_tests_name ON sample_tests(test_name);

        CREATE TABLE sample_genes (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            sample_id       uuid NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
            gene            text NOT NULL,
            purpose         text NOT NULL CHECK (purpose IN
                ('identificacao','resistencia','producao_enzima','outro')),
            result          text,
            ncbi_accession  text,
            method          text,
            tested_at       date,
            notes           text,
            created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_sample_genes_sample ON sample_genes(sample_id);
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
    op.execute("DROP TABLE IF EXISTS sample_genes")
    op.execute("DROP TABLE IF EXISTS sample_tests")
    op.execute(
        """
        ALTER TABLE samples
            DROP COLUMN IF EXISTS organism_type,
            DROP COLUMN IF EXISTS colonia_forma,
            DROP COLUMN IF EXISTS colonia_elevacao,
            DROP COLUMN IF EXISTS colonia_margem,
            DROP COLUMN IF EXISTS colonia_cor,
            DROP COLUMN IF EXISTS colonia_textura,
            DROP COLUMN IF EXISTS colonia_tamanho_mm,
            DROP COLUMN IF EXISTS colonia_opacidade;
        """
    )
