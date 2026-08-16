"""job_status: NOTIFY em toda mudança de status de pipeline_jobs

`new_job` (0001) só dispara em INSERT — serve pro worker saber que tem job
novo pra pegar. O que falta pro usuário acompanhar o progresso em tempo real
(em vez de dar poll em GET /{job_id}) é um canal que dispare em toda transição
de status: queued -> running -> completed/failed/dead_letter, e também nos
reenfileiramentos do reaper.

Payload: "{job_id}:{status}:{organization_id}" — o WS handler (jobs/router.py)
faz o filtro por organização na aplicação, já que pg_notify não passa pela RLS.

Revision ID: 0003_job_status_notify
Revises: 0002_auth_role_invites
"""
from alembic import op

revision = "0003_job_status_notify"
down_revision = "0002_auth_role_invites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION notify_job_status() RETURNS TRIGGER AS $$
        BEGIN
            PERFORM pg_notify(
                'job_status',
                NEW.id::text || ':' || NEW.status || ':' || NEW.organization_id::text
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_notify_job_status
        AFTER INSERT OR UPDATE OF status ON pipeline_jobs
        FOR EACH ROW EXECUTE FUNCTION notify_job_status();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_notify_job_status ON pipeline_jobs")
    op.execute("DROP FUNCTION IF EXISTS notify_job_status() CASCADE")
