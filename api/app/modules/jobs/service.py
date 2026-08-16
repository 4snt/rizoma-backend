"""Fila de jobs — enqueue, dequeue atômico, heartbeat, retry com backoff.

Duas populações usam este módulo e elas NÃO são iguais — decisão de
infraestrutura, não de domínio, por isso permanece explícita aqui:

  * Usuários (enqueue/list/cancel) falam pelo papel `rizoma_app`, com RLS ligada.
    Cada um só enxerga a própria organização.
  * O R Worker é cross-org por natureza — ele puxa o próximo job da fila global,
    seja de que organização for. Para isso existe o papel `rizoma_system`
    (BYPASSRLS), com engine próprio aqui. Autenticação por token compartilhado:
    o worker não é um usuário e não tem JWT.
"""
from uuid import UUID

from fastapi import Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.modules.interop.service import dispatch_event
from app.modules.jobs.domain.entities import AnalysisResult, Job, assert_cancellable, resolve_failure
from app.modules.jobs.domain.exceptions import JobRunningError, NotCancellableError
from app.modules.jobs.repository import PgJobRepository
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


def _job_out(job: Job) -> JobOut:
    return JobOut(**job.to_dict())


# ── Usuário ─────────────────────────────────────────────────────────────
async def enqueue(ctx: Ctx, req: EnqueueRequest) -> JobOut:
    ctx.require("job:write")
    repo = PgJobRepository(ctx.session)
    job = Job(
        id=new_id(),
        organization_id=ctx.org_id,
        project_id=req.project_id,
        job_type=req.job_type,
        status="queued",
        priority=req.priority,
        attempts=0,
        max_attempts=settings.job_max_attempts,
        payload=req.payload,
        created_by=ctx.user_id,
    )
    saved = await repo.create_queued(job)
    return _job_out(saved)


async def get_user_org_ids(user_id: UUID) -> set[UUID]:
    """Orgs do usuário, via papel system (BYPASSRLS) — usado pelo WS de status
    antes de qualquer contexto de tenant existir (a conexão de LISTEN é global).
    """
    async with system_sessionmaker()() as session:
        rows = (
            await session.execute(
                text("SELECT organization_id FROM organization_members WHERE user_id = :u"),
                {"u": str(user_id)},
            )
        ).scalars().all()
    return {UUID(str(r)) for r in rows}


async def list_jobs(ctx: Ctx, project_id: UUID | None, status_filter: str | None) -> list[JobOut]:
    ctx.require("job:read")
    repo = PgJobRepository(ctx.session)
    return [_job_out(j) for j in await repo.list_jobs(project_id, status_filter)]


async def get_job(ctx: Ctx, job_id: UUID) -> JobDetailOut:
    ctx.require("job:read")
    repo = PgJobRepository(ctx.session)
    job = await repo.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job não encontrado.")

    results = await repo.list_results(job_id)
    return JobDetailOut(
        **_job_out(job).model_dump(),
        results=[AnalysisResultOut(**r.to_dict()) for r in results],
    )


async def cancel(ctx: Ctx, job_id: UUID) -> JobOut:
    ctx.require("job:write")
    repo = PgJobRepository(ctx.session)
    current_status = await repo.get_status(job_id)
    if current_status is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job não encontrado.")

    try:
        assert_cancellable(current_status)
    except (JobRunningError, NotCancellableError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))

    updated = await repo.cancel(job_id)
    return _job_out(updated)


# ── Worker (rizoma_system, cross-org) ───────────────────────────────────
async def dequeue(worker_id: str) -> JobOut | None:
    """Dequeue atômico. `FOR UPDATE SKIP LOCKED` é o que permite N workers
    concorrendo na mesma fila sem que dois peguem o mesmo job."""
    async with system_sessionmaker()() as session:
        async with session.begin():
            repo = PgJobRepository(session)
            job = await repo.dequeue_next(worker_id)
            if job is None:
                return None
            files = await repo.worker_input_files(job.project_id)

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
    return _job_out(job)


async def heartbeat(job_id: UUID, req: HeartbeatRequest) -> JobOut:
    async with system_sessionmaker()() as session:
        async with session.begin():
            repo = PgJobRepository(session)
            job = await repo.touch_heartbeat(job_id, req.progress_pct, req.progress_stage)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job não encontrado.")
    return _job_out(job)


async def complete(job_id: UUID, req: CompleteRequest) -> JobOut:
    async with system_sessionmaker()() as session:
        async with session.begin():
            repo = PgJobRepository(session)
            org_id = await repo.get_organization_id(job_id)
            if org_id is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Job não encontrado.")

            await repo.insert_analysis_result(
                AnalysisResult(
                    id=new_id(),
                    organization_id=org_id,
                    job_id=job_id,
                    analysis_type=req.analysis_type,
                    result_data=req.result_data,
                )
            )

            summary = req.result_summary or {"analysis_type": req.analysis_type}
            job = await repo.mark_completed(job_id, summary)
        await dispatch_event(session, org_id, "job.completed", {"job_id": str(job_id), "job_type": job.job_type})
    return _job_out(job)


async def fail(job_id: UUID, req: FailRequest) -> JobOut:
    async with system_sessionmaker()() as session:
        async with session.begin():
            repo = PgJobRepository(session)
            attempts_info = await repo.get_attempts(job_id)
            if attempts_info is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Job não encontrado.")
            attempts, max_attempts = attempts_info

            decision = resolve_failure(
                attempts=attempts,
                max_attempts=max_attempts,
                error_code=req.error_code,
                error_message=req.error_message,
            )
            if decision.status == "retry_scheduled":
                job = await repo.schedule_retry(
                    job_id,
                    next_retry_at=decision.next_retry_at,
                    error_code=decision.error_code,
                    error_message=decision.error_message,
                )
            else:
                job = await repo.mark_dead_letter(
                    job_id, error_code=decision.error_code, error_message=decision.error_message
                )
        # Só dispara webhook na falha DEFINITIVA (dead_letter) — em retry ainda
        # vai tentar de novo, avisar o assinante agora seria falso-positivo.
        if decision.status != "retry_scheduled":
            await dispatch_event(
                session, job.organization_id, "job.failed",
                {"job_id": str(job_id), "job_type": job.job_type, "error_code": decision.error_code},
            )
    return _job_out(job)
