"""MVP baseline — Rizoma v2 (Fase 0 + Fatia 1)

Substitui as 9 migrations SQL soltas (que tinham DUAS com o número 004 e
nenhum registro confiável de ordem).

Decisões materializadas aqui:
  ADR-001  arquivos em MinIO; catálogo de metadados no PG. Sem Large Objects.
  ADR-006  resultados de laboratório são append-only e versionados (ISO 17025).
  ADR-007  UUIDv7 + organization_id em toda tabela + RLS forçada.

Revision ID: 0001_mvp_baseline
"""
from alembic import op

revision = "0001_mvp_baseline"
down_revision = None
branch_labels = None
depends_on = None


# Tabelas com escopo de organização. Toda uma delas ganha RLS.
TENANT_TABLES = [
    "customers",
    "projects",
    "samples",
    "files",
    "pipeline_jobs",
    "analysis_results",
    "lab_results",
    "result_versions",
    "custody_events",
    "reports",
    "audit_log",
    "organization_members",
    "invitations",
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # ── Papel de runtime ────────────────────────────────────────────────
    # NOSUPERUSER e NOBYPASSRLS explícitos: é o que faz a RLS valer de fato.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rizoma_app') THEN
                CREATE ROLE rizoma_app LOGIN PASSWORD 'rizoma_app_pw'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            ELSE
                ALTER ROLE rizoma_app NOSUPERUSER NOBYPASSRLS;
            END IF;
        END$$;
        """
    )

    # ── Identidade (global, sem organização) ────────────────────────────
    op.execute(
        """
        CREATE TABLE organizations (
            id          uuid PRIMARY KEY,
            slug        text NOT NULL UNIQUE,
            name        text NOT NULL,
            cnpj        text,
            is_active   boolean NOT NULL DEFAULT true,
            created_at  timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE users (
            id          uuid PRIMARY KEY,
            email       citext_placeholder,
            name        text NOT NULL,
            google_sub  text UNIQUE,
            avatar_url  text,
            is_active   boolean NOT NULL DEFAULT true,
            created_at  timestamptz NOT NULL DEFAULT now(),
            last_login  timestamptz
        );
        """.replace("citext_placeholder", "text NOT NULL UNIQUE")
    )

    # Papéis do §12.2 do plano, reduzidos ao que a Fatia 1 realmente usa.
    op.execute(
        """
        CREATE TABLE organization_members (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role            text NOT NULL CHECK (role IN (
                                'org_admin','coordinator','tech_responsible',
                                'field_tech','lab_tech','bioinformatician','client','viewer')),
            created_at      timestamptz NOT NULL DEFAULT now(),
            UNIQUE (organization_id, user_id)
        );

        CREATE TABLE invitations (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            email           text NOT NULL,
            role            text NOT NULL,
            invited_by      uuid REFERENCES users(id) ON DELETE SET NULL,
            invited_at      timestamptz NOT NULL DEFAULT now(),
            accepted_at     timestamptz,
            UNIQUE (organization_id, email)
        );
        """
    )

    # ── Comercial mínimo ────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE customers (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name            text NOT NULL,
            document        text,
            contact_email   text,
            contact_phone   text,
            notes           text,
            created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            UNIQUE (organization_id, name)
        );
        """
    )

    # ── Projeto: a unidade central ──────────────────────────────────────
    op.execute(
        """
        CREATE TABLE projects (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            customer_id     uuid REFERENCES customers(id) ON DELETE SET NULL,
            code            text NOT NULL,
            name            text NOT NULL,
            description     text NOT NULL DEFAULT '',
            marker_type     text CHECK (marker_type IN ('16S','ITS','RNA')),
            status          text NOT NULL DEFAULT 'draft' CHECK (status IN (
                                'draft','planning','approved','in_progress',
                                'under_review','completed','cancelled','archived')),
            dada2_params    jsonb NOT NULL DEFAULT '{}',
            created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            UNIQUE (organization_id, code)
        );
        CREATE INDEX idx_projects_org ON projects(organization_id);
        """
    )

    # ── Amostras ────────────────────────────────────────────────────────
    # occurred_at != recorded_at: o técnico coleta às 9h sem sinal e sincroniza
    # às 18h. Os dois instantes importam (bitemporalidade).
    op.execute(
        """
        CREATE TABLE samples (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id      uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            code            text NOT NULL,
            matrix          text NOT NULL CHECK (matrix IN (
                                'solo','sedimento','agua','tecido_vegetal','raiz','folha',
                                'biomassa','cultura_microbiana','dna','rna','extrato',
                                'biochar','formulado','substrato')),
            treatment_group text,
            replicate       int,
            status          text NOT NULL DEFAULT 'planned' CHECK (status IN (
                                'planned','collected','in_transit','received','accepted',
                                'rejected','processing','analyzed','stored','consumed','disposed')),
            geom            geography(Point, 4326),
            collected_by    uuid REFERENCES users(id) ON DELETE SET NULL,
            occurred_at     timestamptz,
            recorded_at     timestamptz NOT NULL DEFAULT now(),
            notes           text,
            created_at      timestamptz NOT NULL DEFAULT now(),
            UNIQUE (organization_id, project_id, code)
        );
        CREATE INDEX idx_samples_project ON samples(project_id);
        CREATE INDEX idx_samples_org ON samples(organization_id);
        CREATE INDEX idx_samples_geom ON samples USING GIST (geom);
        """
    )

    # ── Catálogo de arquivos (ADR-001) ──────────────────────────────────
    # O byte mora no MinIO. Aqui mora só o metadado — e o sha256, que é o que
    # permite provar depois que o arquivo não mudou.
    op.execute(
        """
        CREATE TABLE files (
            id               uuid PRIMARY KEY,
            organization_id  uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id       uuid REFERENCES projects(id) ON DELETE CASCADE,
            sample_id        uuid REFERENCES samples(id) ON DELETE CASCADE,
            category         text NOT NULL CHECK (category IN (
                                'fastq_r1','fastq_r2','phyloseq','result','report',
                                'field_photo','document','other')),
            original_name    text NOT NULL,
            storage_key      text NOT NULL UNIQUE,
            mime_type        text,
            size_bytes       bigint,
            sha256           text,
            upload_status    text NOT NULL DEFAULT 'pending'
                             CHECK (upload_status IN ('pending','uploaded','failed')),
            created_by       uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at       timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_files_sample ON files(sample_id);
        CREATE INDEX idx_files_project ON files(project_id);
        """
    )

    # ── Fila de jobs ────────────────────────────────────────────────────
    # Estados completos do §10.2 do plano. heartbeat_at + worker_id existem para
    # o reaper: sem ele, um worker que morre no meio de um SpiecEasi de 20min
    # deixa o job travado em 'running' para sempre.
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
        """
    )

    # ── Resultados de laboratório: append-only (ADR-006) ────────────────
    # `lab_results` é só a identidade do resultado. O VALOR mora em
    # result_versions e nunca é sobrescrito — corrigir cria versão nova
    # apontando para a anterior. É o que a ISO 17025 exige e o que um UPDATE
    # destruiria.
    op.execute(
        """
        CREATE TABLE lab_results (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            sample_id       uuid NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
            analyte         text NOT NULL,
            method          text,
            created_at      timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE result_versions (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            result_id       uuid NOT NULL REFERENCES lab_results(id) ON DELETE CASCADE,
            version         int  NOT NULL,
            value_numeric   numeric,
            value_text      text,
            unit            text NOT NULL,
            lod             numeric,
            loq             numeric,
            uncertainty     numeric,
            below_lod       boolean NOT NULL DEFAULT false,
            status          text NOT NULL DEFAULT 'submitted' CHECK (status IN (
                                'draft','submitted','reviewed','approved','retracted')),
            supersedes      uuid REFERENCES result_versions(id),
            change_reason   text,
            created_by      uuid NOT NULL REFERENCES users(id),
            reviewed_by     uuid REFERENCES users(id),
            created_at      timestamptz NOT NULL DEFAULT now(),
            UNIQUE (result_id, version),
            -- Corrigir um resultado exige justificativa. Sem isso, a trilha não
            -- explica NADA para um auditor.
            CONSTRAINT chk_reason_on_correction
                CHECK (supersedes IS NULL OR change_reason IS NOT NULL),
            -- Segregação de funções: quem produz não aprova.
            CONSTRAINT chk_segregation
                CHECK (reviewed_by IS NULL OR reviewed_by <> created_by)
        );
        CREATE INDEX idx_rv_result ON result_versions(result_id);
        """
    )

    # UPDATE e DELETE em result_versions são proibidos no nível do BANCO.
    # Não adianta um dev distraído: o Postgres recusa.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'Tabela % é append-only (ADR-006 / ISO 17025). Crie uma versão nova em vez de %.',
                TG_TABLE_NAME, TG_OP;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_result_versions_append_only
        BEFORE UPDATE OR DELETE ON result_versions
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
        """
    )

    # ── Cadeia de custódia: log encadeado ───────────────────────────────
    # prev_hash encadeia os eventos. Adulterar um evento no meio quebra a
    # cadeia e fica detectável.
    op.execute(
        """
        CREATE TABLE custody_events (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            sample_id       uuid NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
            seq             int  NOT NULL,
            event_type      text NOT NULL CHECK (event_type IN (
                                'coleta','transporte','recebimento','transferencia',
                                'processamento','armazenamento','retirada','devolucao','descarte')),
            from_custodian  uuid REFERENCES users(id) ON DELETE SET NULL,
            to_custodian    uuid REFERENCES users(id) ON DELETE SET NULL,
            occurred_at     timestamptz NOT NULL,
            recorded_at     timestamptz NOT NULL DEFAULT now(),
            geom            geography(Point, 4326),
            temperature_c   numeric,
            condition       text,
            notes           text,
            prev_hash       text,
            hash            text NOT NULL,
            UNIQUE (sample_id, seq)
        );
        CREATE INDEX idx_custody_sample ON custody_events(sample_id, seq);

        CREATE TRIGGER trg_custody_append_only
        BEFORE UPDATE OR DELETE ON custody_events
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
        """
    )

    # ── Laudos ──────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE reports (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id      uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            code            text NOT NULL,
            version         int  NOT NULL DEFAULT 1,
            title           text NOT NULL,
            status          text NOT NULL DEFAULT 'draft'
                            CHECK (status IN ('draft','under_review','approved','published','retracted')),
            content         jsonb NOT NULL DEFAULT '{}',
            storage_key     text,
            sha256          text,
            signed_by       uuid REFERENCES users(id) ON DELETE SET NULL,
            signed_at       timestamptz,
            created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            UNIQUE (organization_id, code, version)
        );
        CREATE INDEX idx_reports_project ON reports(project_id);
        """
    )

    # ── Auditoria ───────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE audit_log (
            id              uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            actor_id        uuid REFERENCES users(id) ON DELETE SET NULL,
            action          text NOT NULL,
            entity_type     text NOT NULL,
            entity_id       uuid,
            before          jsonb,
            after           jsonb,
            reason          text,
            ip              inet,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_audit_org_time ON audit_log(organization_id, created_at DESC);
        CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);

        CREATE TRIGGER trg_audit_append_only
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
        """
    )

    # ── Idempotência (sincronização offline do campo) ───────────────────
    # O tablet reenvia a mesma mutação depois de um timeout. Sem isto, a amostra
    # entra duas vezes.
    op.execute(
        """
        CREATE TABLE idempotency_keys (
            key             text PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            user_id         uuid REFERENCES users(id) ON DELETE SET NULL,
            endpoint        text NOT NULL,
            response_status int,
            response_body   jsonb,
            created_at      timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    # ── Row-Level Security ──────────────────────────────────────────────
    # FORCE porque o dono da tabela, por padrão, ignora as próprias policies.
    # A policy lê o GUC que tenancy.bind_tenant() grava com SET LOCAL.
    #
    # NÃO existe GUC de "bypass" aqui, e isso é deliberado. Um GUC customizado
    # pode ser setado por QUALQUER usuário — `SET rizoma.bypass_rls='on'` seria
    # uma porta destrancada que anula todo o isolamento com uma linha de SQL.
    # Quem precisa cruzar organizações usa o papel rizoma_system (abaixo), e a
    # permissão passa a ser do BANCO, não de uma variável que o atacante controla.
    for table in TENANT_TABLES:
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

    # Exceção necessária: no login o usuário ainda não escolheu organização, então
    # não há `current_org` para a policy acima casar. Sem esta segunda policy
    # (permissivas são OR), ninguém conseguiria descobrir a que orgs pertence.
    op.execute(
        """
        CREATE POLICY own_memberships ON organization_members
        FOR SELECT
        USING (user_id = NULLIF(current_setting('rizoma.current_user', true), '')::uuid)
        """
    )

    # Papel de sistema: trabalho legitimamente cross-org (reaper de jobs órfãos).
    # BYPASSRLS é um atributo do PAPEL — não dá para se auto-conceder via SET.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rizoma_system') THEN
                CREATE ROLE rizoma_system LOGIN PASSWORD 'rizoma_system_pw'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;
            ELSE
                ALTER ROLE rizoma_system BYPASSRLS;
            END IF;
        END$$;
        """
    )

    op.execute(
        """
        GRANT USAGE ON SCHEMA public TO rizoma_app, rizoma_system;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
            TO rizoma_app, rizoma_system;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO rizoma_app, rizoma_system;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rizoma_app, rizoma_system;
        """
    )


def downgrade() -> None:
    for table in [
        "idempotency_keys", "audit_log", "reports", "custody_events",
        "result_versions", "lab_results", "analysis_results", "pipeline_jobs",
        "files", "samples", "projects", "customers", "invitations",
        "organization_members", "users", "organizations",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS forbid_mutation() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS notify_new_job() CASCADE")
