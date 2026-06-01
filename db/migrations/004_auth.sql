-- Migration 004: Authentication tables
-- Users table
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       VARCHAR(255) NOT NULL UNIQUE,
    name        VARCHAR(255) NOT NULL,
    google_sub  VARCHAR(255) UNIQUE,
    role        VARCHAR(20) NOT NULL DEFAULT 'researcher'
                CHECK (role IN ('researcher', 'admin')),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login  TIMESTAMPTZ
);

-- Invited users table
CREATE TABLE invited_users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       VARCHAR(255) NOT NULL UNIQUE,
    role        VARCHAR(20) NOT NULL DEFAULT 'researcher',
    invited_by  UUID REFERENCES users(id),
    invited_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    used_at     TIMESTAMPTZ
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_invited_email ON invited_users(email);

GRANT SELECT, INSERT, UPDATE ON users, invited_users TO api_user;
