ALTER TABLE projects ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS project_analyses (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    analysis_type   VARCHAR(50) NOT NULL,
    charts          TEXT[]      NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, analysis_type)
);

CREATE INDEX IF NOT EXISTS idx_project_analyses_project_id ON project_analyses(project_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON project_analyses TO api_user;
GRANT SELECT, INSERT, UPDATE           ON project_analyses TO r_worker;
GRANT SELECT                           ON project_analyses TO readonly;
