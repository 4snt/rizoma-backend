CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE projects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code        VARCHAR(50)  NOT NULL UNIQUE,
    name        VARCHAR(255) NOT NULL,
    marker_type VARCHAR(10)  NOT NULL CHECK (marker_type IN ('16S', 'ITS')),
    status      VARCHAR(20)  NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE samples (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID         NOT NULL REFERENCES projects(id),
    filename        VARCHAR(255) NOT NULL,
    treatment_group VARCHAR(50)  NOT NULL,
    replicate       INT          NOT NULL,
    fastq_r1_key    TEXT         NOT NULL,
    fastq_r2_key    TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
