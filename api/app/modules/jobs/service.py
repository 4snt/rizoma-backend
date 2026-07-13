"""Fila de jobs — enqueue, dequeue atômico, heartbeat, retry com backoff.

Duas populações usam este módulo e elas NÃO são iguais:

  * Usuários (enqueue/list/cancel) falam pelo papel `rizoma_app`, com RLS ligada.
    Cada um só enxerga a própria organização.
  * O R Worker é cross-org por natureza — ele puxa o próximo job da fila global,
    seja de que organização for. Para isso existe o papel `rizoma_system`
    (BYPASSRLS), com engine próprio aqui. Autenticação por token compartilhado:
    o worker não é um usuário e não tem JWT.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.shared import storage
from app.shared.context import Ctx
from app.shared.ids import new_id

from .schemas import (
    AnalysisResultOut,
    CompleteRequest,
    EnqueueRequest,
    FailRequest,
    HeartbeatRequest,
    JobDetailOut,
    JobOut,
)

# Categorias que o worker precisa BAIXAR para trabalhar. Um FASTQ não mora no
# banco: o worker recebe uma URL assinada interna e lê direto do MinIO.
WORKER_INPUT_CATEGORIES = ("fastq_r1", "fastq_r2", "phyloseq")

JOB_COLUMNS = (
    "id, organization_id, project_id, job_type, status, priority, attempts, max_attempts, "
    "payload, progress_pct, progress_stage, queued_at, started_at, finished_at, "
    "next_retry_at, heartbeat_at, worker_id, error_code, error_message, result_summary, "
    "created_by, created_at"
)

_system_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_system_engine_instance: AsyncEngine | None = None


def _system_dsn() -> str:
    return (
        f"postgresql+asyncpg://{settings.system_db_user}:{settings.system_db_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def _system_engine() -> AsyncEngine:
    global _system_engine_instance
    if _system_engine_instance is None:
        _system_engine_instance = create_async_engine(
            _system_dsn(), pool_size=5, max_overflow=2, pool_pre_ping=True
        )
    return _system_engine_instance


def system_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _system_sessionmaker
    if _system_sessionmaker is None:
        _system_sessionmaker = async_sessionmaker(
            _system_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _system_sessionmaker


async def dispose_system_engine() -> None:
    global _system_engine_instance, _system_sessionmaker
    if _system_engine_instance is not None:
        await _system_engine_instance.dispose()
    _system_engine_instance = None
    _system_sessionmaker = None


def require_worker_token(x_worker_token: str | None = Header(default=None, alias="X-Worker-Token")):
    if x_worker_token != settings.worker_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de worker inválido.")
    return x_worker_token


def _jsonb(value: Any) -> Any:
    """asyncpg devolve jsonb como texto quando não há tipagem no statement."""
    if isinstance(value, (str, bytes)):
        return json.loads(value)
    return value


def _to_job(row) -> JobOut:
    d = dict(row)
    d["payload"] = _jsonb(d.get("payload")) or {}
    d["result_summary"] = _jsonb(d.get("result_summary"))
    return JobOut(**d)


# ── Usuário ─────────────────────────────────────────────────────────────
async def enqueue(ctx: Ctx, req: EnqueueRequest) -> JobOut:
    ctx.require("job:write")
    job_id = new_id()
    row = (
        await ctx.session.execute(
            text(
                "INSERT INTO pipeline_jobs (id, organization_id, project_id, job_type, "
                "status, priority, max_attempts, payload, created_by) "
                "VALUES (:id, :org, :proj, :jt, 'queued', :prio, :maxatt, CAST(:payload AS jsonb), :usr) "
                f"RETURNING {JOB_COLUMNS}"
            ),
            {
                "id": str(job_id),
                "org": str(ctx.org_id),
                "proj": str(req.project_id),
                "jt": req.job_type,
                "prio": req.priority,
                "maxatt": settings.job_max_attempts,
                "payload": json.dumps(req.payload),
                "usr": str(ctx.user_id),
            },
        )
    ).mappings().first()
    return _to_job(row)


async def list_jobs(ctx: Ctx, project_id: UUID | None, status_filter: str | None) -> list[JobOut]:
    ctx.require("job:read")
    rows = (
        await ctx.session.execute(
            text(
                f"SELECT {JOB_COLUMNS} FROM pipeline_jobs "
                "WHERE (CAST(:proj AS uuid) IS NULL OR project_id = CAST(:proj AS uuid)) "
                "  AND (CAST(:st AS text) IS NULL OR status = CAST(:st AS text)) "
                "ORDER BY queued_at DESC"
            ),
            {"proj": str(project_id) if project_id else None, "st": status_filter},
        )
    ).mappings().all()
    return [_to_job(r) for r in rows]


async def get_job(ctx: Ctx, job_id: UUID) -> JobDetailOut:
    ctx.require("job:read")
    row = (
        await ctx.session.execute(
            text(f"SELECT {JOB_COLUMNS} FROM pipeline_jobs WHERE id = :id"),
            {"id": str(job_id)},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job não encontrado.")

    results = (
        await ctx.session.execute(
            text(
                "SELECT id, job_id, analysis_type, result_data, created_at "
                "FROM analysis_results WHERE job_id = :id ORDER BY created_at"
            ),
            {"id": str(job_id)},
        )
    ).mappings().all()

    job = _to_job(row)
    return JobDetailOut(
        **job.model_dump(),
        results=[
            AnalysisResultOut(
                id=r["id"],
                job_id=r["job_id"],
                analysis_type=r["analysis_type"],
                result_data=_jsonb(r["result_data"]) or {},
                created_at=r["created_at"],
            )
            for r in results
        ],
    )


async def cancel(ctx: Ctx, job_id: UUID) -> JobOut:
    ctx.require("job:write")
    row = (
        await ctx.session.execute(
            text("SELECT status FROM pipeline_jobs WHERE id = :id"), {"id": str(job_id)}
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job não encontrado.")

    if row["status"] == "running":
        # Não há como matar o processo do worker a partir daqui. Prometer que
        # cancelou seria mentira; 409 é a resposta honesta.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Job já está em execução — não pode ser cancelado pela API.",
        )
    if row["status"] not in ("queued", "retry_scheduled"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Job em estado '{row['status']}' não pode ser cancelado.",
        )

    updated = (
        await ctx.session.execute(
            text(
                "UPDATE pipeline_jobs SET status = 'cancelled', finished_at = now() "
                f"WHERE id = :id RETURNING {JOB_COLUMNS}"
            ),
            {"id": str(job_id)},
        )
    ).mappings().first()
    return _to_job(updated)


# ── Worker (rizoma_system, cross-org) ───────────────────────────────────
async def dequeue(worker_id: str) -> JobOut | None:
    """Dequeue atômico. `FOR UPDATE SKIP LOCKED` é o que permite N workers
    concorrendo na mesma fila sem que dois peguem o mesmo job."""
    async with system_sessionmaker()() as session:
        async with session.begin():
            row = (
                await session.execute(
                    text(
                        "UPDATE pipeline_jobs SET status='running', started_at=now(), "
                        "heartbeat_at=now(), worker_id=:wid, attempts=attempts+1 "
                        "WHERE id = (SELECT id FROM pipeline_jobs "
                        "            WHERE status='queued' "
                        "               OR (status='retry_scheduled' AND next_retry_at <= now()) "
                        "            ORDER BY priority, queued_at "
                        "            FOR UPDATE SKIP LOCKED LIMIT 1) "
                        f"RETURNING {JOB_COLUMNS}"
                    ),
                    {"wid": worker_id},
                )
            ).mappings().first()
            if row is None:
                return None

            job = _to_job(row)
            files = (
                await session.execute(
                    text(
                        "SELECT id, category, original_name, storage_key "
                        "FROM files WHERE project_id = :proj "
                        "  AND upload_status = 'uploaded' "
                        "  AND category = ANY(CAST(:cats AS text[]))"
                    ),
                    {"proj": str(job.project_id), "cats": list(WORKER_INPUT_CATEGORIES)},
                )
            ).mappings().all()

    # URL INTERNA: o worker vive na rede de containers e enxerga outro host que
    # não o do browser. Assinar com o host público daria 403 lá dentro.
    job.payload = dict(job.payload)
    job.payload["input_files"] = [
        {
            "file_id": str(f["id"]),
            "category": f["category"],
            "original_name": f["original_name"],
            "url": storage.presign_download_internal(f["storage_key"]),
        }
        for f in files
    ]
    return job


async def heartbeat(job_id: UUID, req: HeartbeatRequest) -> JobOut:
    async with system_sessionmaker()() as session:
        async with session.begin():
            row = (
                await session.execute(
                    text(
                        "UPDATE pipeline_jobs SET heartbeat_at = now(), "
                        "progress_pct = COALESCE(:pct, progress_pct), "
                        "progress_stage = COALESCE(:stage, progress_stage) "
                        f"WHERE id = :id RETURNING {JOB_COLUMNS}"
                    ),
                    {"pct": req.progress_pct, "stage": req.progress_stage, "id": str(job_id)},
                )
            ).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job não encontrado.")
    return _to_job(row)


async def complete(job_id: UUID, req: CompleteRequest) -> JobOut:
    async with system_sessionmaker()() as session:
        async with session.begin():
            job = (
                await session.execute(
                    text("SELECT organization_id FROM pipeline_jobs WHERE id = :id"),
                    {"id": str(job_id)},
                )
            ).mappings().first()
            if job is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Job não encontrado.")

            await session.execute(
                text(
                    "INSERT INTO analysis_results (id, organization_id, job_id, analysis_type, result_data) "
                    "VALUES (:id, :org, :job, :at, CAST(:data AS jsonb))"
                ),
                {
                    "id": str(new_id()),
                    "org": str(job["organization_id"]),
                    "job": str(job_id),
                    "at": req.analysis_type,
                    "data": json.dumps(req.result_data),
                },
            )

            summary = req.result_summary or {"analysis_type": req.analysis_type}
            row = (
                await session.execute(
                    text(
                        "UPDATE pipeline_jobs SET status='completed', finished_at=now(), "
                        "progress_pct=100, result_summary=CAST(:summary AS jsonb) "
                        f"WHERE id = :id RETURNING {JOB_COLUMNS}"
                    ),
                    {"summary": json.dumps(summary), "id": str(job_id)},
                )
            ).mappings().first()
    return _to_job(row)


def _backoff(attempts: int) -> timedelta:
    """Backoff exponencial: 2^attempts minutos, teto de 1h. Retentar de imediato
    um worker que acabou de cair só derruba o próximo."""
    minutes = min(2 ** max(attempts, 0), 60)
    return timedelta(minutes=minutes)


async def fail(job_id: UUID, req: FailRequest) -> JobOut:
    async with system_sessionmaker()() as session:
        async with session.begin():
            cur = (
                await session.execute(
                    text("SELECT attempts, max_attempts FROM pipeline_jobs WHERE id = :id"),
                    {"id": str(job_id)},
                )
            ).mappings().first()
            if cur is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Job não encontrado.")

            if cur["attempts"] < cur["max_attempts"]:
                next_retry = datetime.now(timezone.utc) + _backoff(cur["attempts"])
                sql = (
                    "UPDATE pipeline_jobs SET status='retry_scheduled', next_retry_at=:nr, "
                    "error_code=:ec, error_message=:em, worker_id=NULL "
                    f"WHERE id = :id RETURNING {JOB_COLUMNS}"
                )
                params = {
                    "nr": next_retry,
                    "ec": req.error_code,
                    "em": req.error_message,
                    "id": str(job_id),
                }
            else:
                # Esgotou as tentativas: sai da fila e vira caso para humano.
                sql = (
                    "UPDATE pipeline_jobs SET status='dead_letter', finished_at=now(), "
                    "error_code=:ec, error_message=:em "
                    f"WHERE id = :id RETURNING {JOB_COLUMNS}"
                )
                params = {"ec": req.error_code, "em": req.error_message, "id": str(job_id)}

            row = (await session.execute(text(sql), params)).mappings().first()
    return _to_job(row)
