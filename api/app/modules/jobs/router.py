"""Rotas da fila de jobs — /api/v2/jobs.

As rotas sob /worker NÃO usam JWT: o R Worker não é um usuário, é um processo.
Autentica com token compartilhado (X-Worker-Token) e trabalha cross-org.
"""
import asyncio
import logging
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query, Response, WebSocket, WebSocketDisconnect, status
from jose import JWTError

from app.core.config import settings
from app.core.security import decode_token
from app.shared.context import Ctx, get_ctx

from . import service
from .schemas import (
    CompleteRequest,
    DequeueRequest,
    EnqueueRequest,
    FailRequest,
    HeartbeatRequest,
    JobDetailOut,
    JobOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/jobs", tags=["jobs"])


@router.post("/enqueue", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def enqueue(req: EnqueueRequest, ctx: Ctx = Depends(get_ctx)) -> JobOut:
    return await service.enqueue(ctx, req)


# ── Worker ──────────────────────────────────────────────────────────────
# Declaradas ANTES de /{job_id}: caso contrário "worker" casaria com o path
# param e o FastAPI tentaria fazer dele um UUID.
@router.post("/worker/dequeue", response_model=JobOut | None,
             dependencies=[Depends(service.require_worker_token)])
async def worker_dequeue(req: DequeueRequest, response: Response) -> JobOut | None:
    job = await service.dequeue(req.worker_id)
    if job is None:
        response.status_code = status.HTTP_204_NO_CONTENT
    return job


@router.post("/worker/{job_id}/heartbeat", response_model=JobOut,
             dependencies=[Depends(service.require_worker_token)])
async def worker_heartbeat(job_id: UUID, req: HeartbeatRequest) -> JobOut:
    return await service.heartbeat(job_id, req)


@router.post("/worker/{job_id}/complete", response_model=JobOut,
             dependencies=[Depends(service.require_worker_token)])
async def worker_complete(job_id: UUID, req: CompleteRequest) -> JobOut:
    return await service.complete(job_id, req)


@router.post("/worker/{job_id}/fail", response_model=JobOut,
             dependencies=[Depends(service.require_worker_token)])
async def worker_fail(job_id: UUID, req: FailRequest) -> JobOut:
    return await service.fail(job_id, req)


# ── Usuário ─────────────────────────────────────────────────────────────
@router.get("/", response_model=list[JobOut])
async def list_jobs(
    project_id: UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    ctx: Ctx = Depends(get_ctx),
) -> list[JobOut]:
    return await service.list_jobs(ctx, project_id, status_filter)


@router.get("/{job_id}", response_model=JobDetailOut)
async def get_job(job_id: UUID, ctx: Ctx = Depends(get_ctx)) -> JobDetailOut:
    return await service.get_job(ctx, job_id)


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel(job_id: UUID, ctx: Ctx = Depends(get_ctx)) -> JobOut:
    return await service.cancel(ctx, job_id)


# ── Status em tempo real ────────────────────────────────────────────────
# WebSocket nativo do browser não manda Authorization — o token vem como
# query param. LISTEN é cross-org por natureza (pg_notify não passa pela
# RLS); o filtro por organização do usuário acontece aqui, na aplicação.
@router.websocket("/ws/status")
async def job_status_ws(websocket: WebSocket, token: str = Query(...)) -> None:
    try:
        payload = decode_token(token)
        user_id = UUID(payload["sub"])
    except (JWTError, KeyError, ValueError):
        await websocket.close(code=4401)
        return

    org_ids = await service.get_user_org_ids(user_id)
    if not org_ids:
        await websocket.close(code=4403)
        return

    await websocket.accept()

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str] = asyncio.Queue()

    def _on_notify(_connection, _pid, _channel, payload_str: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, payload_str)

    conn = await asyncpg.connect(dsn=settings.system_dsn_raw)
    await conn.add_listener("job_status", _on_notify)
    try:
        while True:
            raw = await queue.get()
            job_id, job_status, org_id = raw.split(":", 2)
            if org_id in {str(o) for o in org_ids}:
                await websocket.send_text(f"status:{job_id}:{job_status}")
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("job_status_ws: encerrando conexão após erro")
    finally:
        await conn.remove_listener("job_status", _on_notify)
        await conn.close()
