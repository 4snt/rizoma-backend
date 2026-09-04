"""Registro de isolados: identidade da cepa, origem/hospedeiro, cultivo,
caracterização microscópica, sequência do gene (FASTA + BLAST) e estoque
de alíquotas.

Por que na própria `samples` e não numa tabela `isolates` à parte: o
isolado É a amostra (matrix `cultura_microbiana`) — a 0010 já tomou essa
decisão pra morfologia de colônia, e separar agora criaria um 1:1 artificial
que todo endpoint teria que juntar. Todos os campos são opcionais: amostra
de solo simplesmente não os preenche.

`sample_genes` passa a guardar a sequência bruta (a 0010 tinha deixado de
fora de propósito, mas sem ela o registro do 16S fica incompleto: o
pesquisador precisa do FASTA pra reanalisar/BLASTar de novo). `sequence_length`
é coluna GERADA pelo banco — nunca diverge da sequência, e a API nem precisa
saber calcular.

`sample_aliquots` é estoque físico (glicerol -80, liofilizado...), mutável e
CRUD normal — mesmo raciocínio de `sample_tests`: não é elo de custódia
legal nem resultado ISO 17025. `UNIQUE (sample_id, label)`: dois tubos com
o mesmo rótulo na mesma cepa é erro de cadastro, não dois tubos.

`files.category` ganha `fasta`, `chromatogram`, `gel_image`, `colony_photo`
e `files.sample_gene_id` liga o cromatograma/FASTA ao gene específico, não
só à amostra. A CHECK de `category` foi criada inline no baseline, então
tem nome gerado pelo Postgres (`files_category_check` hoje) — a migration
descobre o nome real via `pg_constraint` em vez de chutar, pra não quebrar
num banco onde o nome saiu diferente.

Revision ID: 0011_isolate_registry
Revises: 0010_sample_biological_data
"""
from alembic import op

revision = "0011_isolate_registry"
down_revision = "0010_sample_biological_data"
branch_labels = None
depends_on = None

TABLES = ["sample_aliquots"]

_CATEGORIES_NEW = (
    "'fastq_r1','fastq_r2','phyloseq','result','report','field_photo','document','other',"
    "'fasta','chromatogram','gel_image','colony_photo'"
)
_CATEGORIES_OLD = (
    "'fastq_r1','fastq_r2','phyloseq','result','report','field_photo','document','other'"
)


def _replace_category_check(categories: str) -> str:
    """Dropa a CHECK de `files.category` seja qual for o nome dela e recria
    com a lista informada. Nome fixo `files_category_check` na recriação
    (coincide com o gerado hoje), pra a próxima migration não precisar
    descobrir de novo."""
    return f"""
        DO $$
        DECLARE
            cname text;
        BEGIN
            FOR cname IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'files'::regclass
                  AND contype = 'c'
                  AND pg_get_constraintdef(oid) LIKE '%category%'
            LOOP
                EXECUTE format('ALTER TABLE files DROP CONSTRAINT %I', cname);
            END LOOP;
            ALTER TABLE files ADD CONSTRAINT files_category_check
                CHECK (category IN ({categories}));
        END $$;
    """


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE samples
            ADD COLUMN strain_name text,
            ADD COLUMN isolation_source text,
            ADD COLUMN host_species text,
            ADD COLUMN host_cultivar text,
            ADD COLUMN collection_site text,
            ADD COLUMN isolated_at date,
            ADD COLUMN culture_medium text,
            ADD COLUMN incubation_temp_c numeric,
            ADD COLUMN incubation_hours numeric,
            ADD COLUMN gram_stain text CHECK (gram_stain IN
                ('positiva','negativa','variavel','nao_aplicavel')),
            ADD COLUMN cell_shape text CHECK (cell_shape IN
                ('bacilo','coco','cocobacilo','espirilo','vibriao','filamentoso',
                 'leveduriforme','hifa','outro')),
            ADD COLUMN motility text CHECK (motility IN ('movel','imovel','nao_testado'));
        """
    )

    op.execute(
        """
        ALTER TABLE sample_genes
            ADD COLUMN sequence text,
            ADD COLUMN sequence_header text,
            ADD COLUMN sequence_length int GENERATED ALWAYS AS (length(sequence)) STORED,
            ADD COLUMN primer_forward text,
            ADD COLUMN primer_reverse text,
            ADD COLUMN blast_top_hit text,
            ADD COLUMN blast_identity_pct numeric CHECK (blast_identity_pct BETWEEN 0 AND 100),
            ADD COLUMN blast_coverage_pct numeric CHECK (blast_coverage_pct BETWEEN 0 AND 100),
            ADD COLUMN blast_hit_accession text;
        """
    )

    op.execute(
        """
        CREATE TABLE sample_aliquots (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            sample_id       uuid NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
            label           text NOT NULL,
            storage_method  text NOT NULL CHECK (storage_method IN
                ('glicerol_-80','glicerol_-20','liofilizado','placa_4c',
                 'oleo_mineral','agua_esteril','outro')),
            freezer         text,
            box             text,
            position        text,
            stored_at       date,
            status          text NOT NULL DEFAULT 'disponivel' CHECK (status IN
                ('disponivel','consumida','descartada','contaminada')),
            notes           text,
            created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            UNIQUE (sample_id, label)
        );
        CREATE INDEX idx_sample_aliquots_sample ON sample_aliquots(sample_id);
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

    op.execute(_replace_category_check(_CATEGORIES_NEW))
    op.execute(
        """
        ALTER TABLE files
            ADD COLUMN sample_gene_id uuid REFERENCES sample_genes(id) ON DELETE SET NULL;
        CREATE INDEX idx_files_gene ON files(sample_gene_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_files_gene")
    op.execute("ALTER TABLE files DROP COLUMN IF EXISTS sample_gene_id")
    # Linhas nas categorias novas violariam a CHECK antiga — viram 'other'
    # em vez de travar o downgrade.
    op.execute(
        "UPDATE files SET category = 'other' "
        "WHERE category IN ('fasta','chromatogram','gel_image','colony_photo')"
    )
    op.execute(_replace_category_check(_CATEGORIES_OLD))

    op.execute("DROP TABLE IF EXISTS sample_aliquots")

    op.execute(
        """
        ALTER TABLE sample_genes
            DROP COLUMN IF EXISTS sequence_length,
            DROP COLUMN IF EXISTS sequence,
            DROP COLUMN IF EXISTS sequence_header,
            DROP COLUMN IF EXISTS primer_forward,
            DROP COLUMN IF EXISTS primer_reverse,
            DROP COLUMN IF EXISTS blast_top_hit,
            DROP COLUMN IF EXISTS blast_identity_pct,
            DROP COLUMN IF EXISTS blast_coverage_pct,
            DROP COLUMN IF EXISTS blast_hit_accession;
        """
    )

    op.execute(
        """
        ALTER TABLE samples
            DROP COLUMN IF EXISTS strain_name,
            DROP COLUMN IF EXISTS isolation_source,
            DROP COLUMN IF EXISTS host_species,
            DROP COLUMN IF EXISTS host_cultivar,
            DROP COLUMN IF EXISTS collection_site,
            DROP COLUMN IF EXISTS isolated_at,
            DROP COLUMN IF EXISTS culture_medium,
            DROP COLUMN IF EXISTS incubation_temp_c,
            DROP COLUMN IF EXISTS incubation_hours,
            DROP COLUMN IF EXISTS gram_stain,
            DROP COLUMN IF EXISTS cell_shape,
            DROP COLUMN IF EXISTS motility;
        """
    )
