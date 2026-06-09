CREATE TABLE pipeline_jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   UUID        NOT NULL REFERENCES projects(id),
    job_type     VARCHAR(50) NOT NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued','running','done','failed')),
    payload      JSONB       NOT NULL DEFAULT '{}',
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_msg    TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pipeline_jobs_status ON pipeline_jobs(status) WHERE status = 'queued';
CREATE INDEX idx_pipeline_jobs_project ON pipeline_jobs(project_id);

CREATE TABLE analysis_results (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id        UUID        NOT NULL REFERENCES pipeline_jobs(id),
    analysis_type VARCHAR(50) NOT NULL,
    result_data   JSONB       NOT NULL DEFAULT '{}',
    es_index_key  TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE network_edges (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id         UUID    NOT NULL REFERENCES pipeline_jobs(id),
    taxa_source    TEXT    NOT NULL,
    taxa_target    TEXT    NOT NULL,
    weight         FLOAT   NOT NULL,
    keystone_score FLOAT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Trigger que notifica o R Worker
CREATE OR REPLACE FUNCTION notify_new_job()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('new_job', NEW.id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_notify_new_job
AFTER INSERT ON pipeline_jobs
FOR EACH ROW
WHEN (NEW.status = 'queued')
EXECUTE FUNCTION notify_new_job();
