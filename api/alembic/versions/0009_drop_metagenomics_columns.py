"""Remove o schema de metagenômica: colunas de `projects` e a fila de análise

O escopo do MVP passou a ser LIMS puro: cadastrar projeto, registrar amostra
e manter a cadeia de custódia. As análises de metagenômica (DADA2, DESeq2,
MaAsLin2, ANCOM-BC2, SpiecEasi, PICRUSt2, FUNGuild) saíram do produto junto
com o R Worker, e com elas:

Colunas de `projects` que só existiam para configurar análise:
- `marker_type`  — 16S/ITS/RNA, marcador do sequenciamento
- `dada2_params` — parâmetros do pipeline DADA2
- `analyses`     — catálogo de análise escolhido na criação (0006)

Tabelas da fila de análise, que só tinham um consumidor — o R Worker:
- `analysis_results` — saída das análises em R
- `pipeline_jobs`    — a fila em si, com o trigger de NOTIFY de 0003

O laudo em PDF deixa de imprimir a linha "Marcador" e a seção "Análises de
bioinformática" (app/modules/reports/pdf.py). Snapshots de laudos já assinados
não são tocados: são JSONB congelado, e o renderizador lê com `.get()`, então
um snapshot antigo que ainda tenha as chaves continua válido — só não ganha as
seções de volta.

Isto APAGA os dados de job e de resultado de análise. O downgrade recria a
estrutura vazia; os valores não voltam.

Revision ID: 0009_drop_metagenomics_columns
Revises: 0008_organization_role_labels
"""
from alembic import op

revision = "0009_drop_metagenomics_columns"
down_revision = "0008_organization_role_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS analyses")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS dada2_params")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS marker_type")

    # CASCADE leva junto os dois triggers (trg_notify_new_job do baseline e
    # trg_notify_job_status de 0003) e a FK de analysis_results.
    op.execute("DROP TABLE IF EXISTS analysis_results CASCADE")
    op.execute("DROP TABLE IF EXISTS pipeline_jobs CASCADE")
    op.execute("DROP FUNCTION IF EXISTS notify_new_job() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS notify_job_status() CASCADE")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE projects ADD COLUMN marker_type text "
        "CHECK (marker_type IN ('16S','ITS','RNA'))"
    )
    op.execute(
        "ALTER TABLE projects ADD COLUMN dada2_params jsonb NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE projects ADD COLUMN analyses jsonb NOT NULL DEFAULT '[]'::jsonb"
    )

    op.execute(
        """
        CREATE TABLE pipeline_jobs (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id      uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            job_type        text NOT NULL,
            status          text NOT NULL DEFAULT 'queued' CHECK (status IN (
                                'queued','running','retry_scheduled','completed',
                                'failed','cancelled','dead_letter')),
            priority        int  NOT NULL DEFAULT 100,
            attempts        int  NOT NULL DEFAULT 0,
            max_attempts    int  NOT NULL DEFAULT 3,
            payload         jsonb NOT NULL DEFAULT '{}',
            progress_pct    int  NOT NULL DEFAULT 0,
            progress_stage  text,
            queued_at       timestamptz NOT NULL DEFAULT now(),
            started_at      timestamptz,
            finished_at     timestamptz,
            next_retry_at   timestamptz,
            heartbeat_at    timestamptz,
            worker_id       text,
            error_code      text,
            error_message   text,
            result_summary  jsonb,
            created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_jobs_dequeue ON pipeline_jobs(priority, queued_at)
            WHERE status IN ('queued','retry_scheduled');
        CREATE INDEX idx_jobs_project ON pipeline_jobs(project_id);
        CREATE INDEX idx_jobs_heartbeat ON pipeline_jobs(heartbeat_at) WHERE status = 'running';

        CREATE TABLE analysis_results (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            job_id          uuid NOT NULL REFERENCES pipeline_jobs(id) ON DELETE CASCADE,
            analysis_type   text NOT NULL,
            result_data     jsonb NOT NULL DEFAULT '{}',
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_results_job ON analysis_results(job_id);
        CREATE INDEX idx_results_data ON analysis_results USING GIN (result_data);
        """
    )

    # Mesma RLS do baseline: sem isto as tabelas voltariam sem isolamento.
    for table in ("pipeline_jobs", "analysis_results"):
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
    op.execute(
        """
        GRANT SELECT, INSERT, UPDATE, DELETE ON pipeline_jobs, analysis_results
            TO rizoma_app, rizoma_system
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION notify_new_job() RETURNS TRIGGER AS $$
        BEGIN
            PERFORM pg_notify('new_job', NEW.id::text);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_notify_new_job
        AFTER INSERT ON pipeline_jobs
        FOR EACH ROW WHEN (NEW.status = 'queued')
        EXECUTE FUNCTION notify_new_job();

        CREATE OR REPLACE FUNCTION notify_job_status() RETURNS TRIGGER AS $$
        BEGIN
            PERFORM pg_notify(
                'job_status',
                NEW.id::text || ':' || NEW.status || ':' || NEW.organization_id::text
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_notify_job_status
        AFTER INSERT OR UPDATE OF status ON pipeline_jobs
        FOR EACH ROW EXECUTE FUNCTION notify_job_status();
        """
    )
