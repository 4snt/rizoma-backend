-- Views analíticas

CREATE OR REPLACE VIEW v_pending_jobs AS
SELECT
    j.id,
    j.project_id,
    p.code AS project_code,
    j.job_type,
    j.status,
    EXTRACT(EPOCH FROM (NOW() - j.created_at)) / 60 AS wait_minutes
FROM pipeline_jobs j
JOIN projects p ON p.id = j.project_id
WHERE j.status = 'queued'
ORDER BY j.created_at;

CREATE OR REPLACE VIEW v_analysis_summary AS
SELECT
    p.code AS project_code,
    r.analysis_type,
    COUNT(*) AS total_runs,
    MAX(j.completed_at) AS last_run
FROM analysis_results r
JOIN pipeline_jobs j ON j.id = r.job_id
JOIN projects p ON p.id = j.project_id
GROUP BY p.code, r.analysis_type;

CREATE OR REPLACE VIEW v_keystone_taxa AS
SELECT
    n.taxa_source AS taxon,
    AVG(n.keystone_score) AS avg_keystone_score,
    COUNT(*) AS degree
FROM network_edges n
GROUP BY n.taxa_source
ORDER BY avg_keystone_score DESC;

CREATE OR REPLACE VIEW v_cross_project AS
SELECT
    p.code AS project_code,
    r.analysis_type,
    r.result_data->>'n_significant' AS n_significant,
    j.completed_at
FROM analysis_results r
JOIN pipeline_jobs j ON j.id = r.job_id
JOIN projects p ON p.id = j.project_id
WHERE j.status = 'done';

-- Roles
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'api_user') THEN
        CREATE ROLE api_user LOGIN PASSWORD 'changeme';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'r_worker') THEN
        CREATE ROLE r_worker LOGIN PASSWORD 'changeme';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'readonly') THEN
        CREATE ROLE readonly LOGIN PASSWORD 'changeme';
    END IF;
END$$;

GRANT SELECT, INSERT, UPDATE ON projects, samples, pipeline_jobs, analysis_results, network_edges TO api_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO api_user;

GRANT SELECT ON pipeline_jobs TO r_worker;
GRANT INSERT, UPDATE ON pipeline_jobs TO r_worker;
GRANT INSERT ON analysis_results, network_edges TO r_worker;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly;
