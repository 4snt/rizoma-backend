"""Persistência da fila de jobs. Todo `sqlalchemy.text()` do módulo mora
aqui — `service.py` só orquestra entidade + repository + a escolha explícita
de sessão (usuário vs worker), que é infraestrutura, não domínio.
"""
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.jobs.domain.entities import (
    WORKER_INPUT_CATEGORIES,
    AnalysisResult,
    Job,
)

_JOB_COLS = (
    "id, organization_id, project_id, job_type, status, priority, attempts, max_attempts, "
    "payload, progress_pct, progress_stage, queued_at, started_at, finished_at, "
    "next_retry_at, heartbeat_at, worker_id, error_code, error_message, result_summary, "
    "created_by, created_at"
)


def _jsonb(value: Any) -> Any:
    """asyncpg devolve jsonb como texto quando não há tipagem no statement."""
    if isinstance(value, (str, bytes)):
        return json.loads(value)
    return value


def _job_from_row(row: dict[str, Any]) -> Job:
    d = dict(row)
    d["payload"] = _jsonb(d.get("payload")) or {}
    d["result_summary"] = _jsonb(d.get("result_summary"))
    return Job(**d)


class PgJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Usuário ───────────────────────────────────────────────────────────
    async def create_queued(self, job: Job) -> Job:
        row = (
            await self.session.execute(
                text(
                    "INSERT INTO pipeline_jobs (id, organization_id, project_id, job_type, "
                    "status, priority, max_attempts, payload, created_by) "
                    "VALUES (:id, :org, :proj, :jt, 'queued', :prio, :maxatt, CAST(:payload AS jsonb), :usr) "
                    f"RETURNING {_JOB_COLS}"
                ),
                {
                    "id": str(job.id),
                    "org": str(job.organization_id),
                    "proj": str(job.project_id),
                    "jt": job.job_type,
                    "prio": job.priority,
                    "maxatt": job.max_attempts,
                    "payload": json.dumps(job.payload),
                    "usr": str(job.created_by) if job.created_by else None,
                },
            )
        ).mappings().first()
        return _job_from_row(dict(row))

    async def list_jobs(self, project_id: UUID | None, status_filter: str | None) -> list[Job]:
        rows = (
            await self.session.execute(
                text(
                    f"SELECT {_JOB_COLS} FROM pipeline_jobs "
                    "WHERE (CAST(:proj AS uuid) IS NULL OR project_id = CAST(:proj AS uuid)) "
                    "  AND (CAST(:st AS text) IS NULL OR status = CAST(:st AS text)) "
                    "ORDER BY queued_at DESC"
                ),
                {"proj": str(project_id) if project_id else None, "st": status_filter},
            )
        ).mappings().all()
        return [_job_from_row(dict(r)) for r in rows]

    async def get(self, job_id: UUID) -> Job | None:
        row = (
            await self.session.execute(
                text(f"SELECT {_JOB_COLS} FROM pipeline_jobs WHERE id = :id"),
                {"id": str(job_id)},
            )
        ).mappings().first()
        return _job_from_row(dict(row)) if row is not None else None

    async def get_status(self, job_id: UUID) -> str | None:
        row = (
            await self.session.execute(
                text("SELECT status FROM pipeline_jobs WHERE id = :id"), {"id": str(job_id)}
            )
        ).mappings().first()
        return row["status"] if row is not None else None

    async def list_results(self, job_id: UUID) -> list[AnalysisResult]:
        rows = (
            await self.session.execute(
                text(
                    "SELECT id, job_id, analysis_type, result_data, created_at "
                    "FROM analysis_results WHERE job_id = :id ORDER BY created_at"
                ),
                {"id": str(job_id)},
            )
        ).mappings().all()
        return [
            AnalysisResult(
                id=r["id"],
                organization_id=None,
                job_id=r["job_id"],
                analysis_type=r["analysis_type"],
                result_data=_jsonb(r["result_data"]) or {},
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def cancel(self, job_id: UUID) -> Job:
        row = (
            await self.session.execute(
                text(
                    "UPDATE pipeline_jobs SET status = 'cancelled', finished_at = now() "
                    f"WHERE id = :id RETURNING {_JOB_COLS}"
                ),
                {"id": str(job_id)},
            )
        ).mappings().first()
        return _job_from_row(dict(row))

    # ── Worker (rizoma_system, cross-org) ────────────────────────────────
    async def dequeue_next(self, worker_id: str) -> Job | None:
        """Dequeue atômico. `FOR UPDATE SKIP LOCKED` é o que permite N
        workers concorrendo na mesma fila sem que dois peguem o mesmo job."""
        row = (
            await self.session.execute(
                text(
                    "UPDATE pipeline_jobs SET status='running', started_at=now(), "
                    "heartbeat_at=now(), worker_id=:wid, attempts=attempts+1 "
                    "WHERE id = (SELECT id FROM pipeline_jobs "
                    "            WHERE status='queued' "
                    "               OR (status='retry_scheduled' AND next_retry_at <= now()) "
                    "            ORDER BY priority, queued_at "
                    "            FOR UPDATE SKIP LOCKED LIMIT 1) "
                    f"RETURNING {_JOB_COLS}"
                ),
                {"wid": worker_id},
            )
        ).mappings().first()
        return _job_from_row(dict(row)) if row is not None else None

    async def worker_input_files(self, project_id: UUID) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                text(
                    "SELECT id, category, original_name, storage_key "
                    "FROM files WHERE project_id = :proj "
                    "  AND upload_status = 'uploaded' "
                    "  AND category = ANY(CAST(:cats AS text[]))"
                ),
                {"proj": str(project_id), "cats": list(WORKER_INPUT_CATEGORIES)},
            )
        ).mappings().all()
        return [dict(r) for r in rows]

    async def touch_heartbeat(self, job_id: UUID, pct: int | None, stage: str | None) -> Job | None:
        row = (
            await self.session.execute(
                text(
                    "UPDATE pipeline_jobs SET heartbeat_at = now(), "
                    "progress_pct = COALESCE(:pct, progress_pct), "
                    "progress_stage = COALESCE(:stage, progress_stage) "
                    f"WHERE id = :id RETURNING {_JOB_COLS}"
                ),
                {"pct": pct, "stage": stage, "id": str(job_id)},
            )
        ).mappings().first()
        return _job_from_row(dict(row)) if row is not None else None

    async def get_organization_id(self, job_id: UUID) -> UUID | None:
        row = (
            await self.session.execute(
                text("SELECT organization_id FROM pipeline_jobs WHERE id = :id"),
                {"id": str(job_id)},
            )
        ).mappings().first()
        return row["organization_id"] if row is not None else None

    async def insert_analysis_result(self, result: AnalysisResult) -> None:
        await self.session.execute(
            text(
                "INSERT INTO analysis_results (id, organization_id, job_id, analysis_type, result_data) "
                "VALUES (:id, :org, :job, :at, CAST(:data AS jsonb))"
            ),
            {
                "id": str(result.id),
                "org": str(result.organization_id),
                "job": str(result.job_id),
                "at": result.analysis_type,
                "data": json.dumps(result.result_data),
            },
        )

    async def mark_completed(self, job_id: UUID, summary: dict[str, Any]) -> Job | None:
        row = (
            await self.session.execute(
                text(
                    "UPDATE pipeline_jobs SET status='completed', finished_at=now(), "
                    "progress_pct=100, result_summary=CAST(:summary AS jsonb) "
                    f"WHERE id = :id RETURNING {_JOB_COLS}"
                ),
                {"summary": json.dumps(summary), "id": str(job_id)},
            )
        ).mappings().first()
        return _job_from_row(dict(row)) if row is not None else None

    async def get_attempts(self, job_id: UUID) -> tuple[int, int] | None:
        row = (
            await self.session.execute(
                text("SELECT attempts, max_attempts FROM pipeline_jobs WHERE id = :id"),
                {"id": str(job_id)},
            )
        ).mappings().first()
        return (row["attempts"], row["max_attempts"]) if row is not None else None

    async def schedule_retry(
        self, job_id: UUID, *, next_retry_at, error_code: str | None, error_message: str | None
    ) -> Job | None:
        row = (
            await self.session.execute(
                text(
                    "UPDATE pipeline_jobs SET status='retry_scheduled', next_retry_at=:nr, "
                    "error_code=:ec, error_message=:em, worker_id=NULL "
                    f"WHERE id = :id RETURNING {_JOB_COLS}"
                ),
                {"nr": next_retry_at, "ec": error_code, "em": error_message, "id": str(job_id)},
            )
        ).mappings().first()
        return _job_from_row(dict(row)) if row is not None else None

    async def mark_dead_letter(
        self, job_id: UUID, *, error_code: str | None, error_message: str | None
    ) -> Job | None:
        row = (
            await self.session.execute(
                text(
                    "UPDATE pipeline_jobs SET status='dead_letter', finished_at=now(), "
                    "error_code=:ec, error_message=:em "
                    f"WHERE id = :id RETURNING {_JOB_COLS}"
                ),
                {"ec": error_code, "em": error_message, "id": str(job_id)},
            )
        ).mappings().first()
        return _job_from_row(dict(row)) if row is not None else None
