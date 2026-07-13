"""Reaper de jobs órfãos.

O problema que ele resolve: um worker que morre no meio de um SpiecEasi de 20
minutos não avisa ninguém. O job fica em 'running' para sempre — nenhum outro
worker o pega (não está mais em 'queued') e nenhum usuário sabe que ele morreu.
A fila vaza capacidade silenciosamente.

O heartbeat é o sinal de vida. Passou do timeout sem bater, o job volta para a
fila — ou vai para dead_letter se já gastou todas as tentativas (um job que
mata o worker toda vez que roda vai matá-lo de novo).

Cross-org por natureza: usa o papel rizoma_system (BYPASSRLS).
"""
import asyncio
import logging

from sqlalchemy import text

from app.core.config import settings

from .service import system_sessionmaker

logger = logging.getLogger(__name__)


async def reap_orphan_jobs() -> dict[str, int]:
    """Devolve {'requeued': n, 'dead_lettered': n}."""
    timeout = settings.job_heartbeat_timeout_seconds

    async with system_sessionmaker()() as session:
        async with session.begin():
            requeued = (
                await session.execute(
                    text(
                        "UPDATE pipeline_jobs SET status='queued', worker_id=NULL, "
                        "started_at=NULL, heartbeat_at=NULL, "
                        "error_code='worker_timeout', "
                        "error_message='Worker parou de responder; job devolvido à fila.' "
                        "WHERE status='running' "
                        "  AND heartbeat_at < now() - make_interval(secs => :t) "
                        "  AND attempts < max_attempts "
                        "RETURNING id"
                    ),
                    {"t": timeout},
                )
            ).scalars().all()

            dead = (
                await session.execute(
                    text(
                        "UPDATE pipeline_jobs SET status='dead_letter', finished_at=now(), "
                        "error_code='worker_timeout', "
                        "error_message='Worker parou de responder e as tentativas acabaram.' "
                        "WHERE status='running' "
                        "  AND heartbeat_at < now() - make_interval(secs => :t) "
                        "  AND attempts >= max_attempts "
                        "RETURNING id"
                    ),
                    {"t": timeout},
                )
            ).scalars().all()

            # O trigger pg_notify só dispara em INSERT. Um job requeued por UPDATE
            # passaria despercebido até o próximo poll — avisamos na mão.
            for job_id in requeued:
                await session.execute(
                    text("SELECT pg_notify('new_job', :id)"), {"id": str(job_id)}
                )

    if requeued or dead:
        logger.warning(
            "Reaper: %d job(s) devolvidos à fila, %d em dead_letter.", len(requeued), len(dead)
        )
    return {"requeued": len(requeued), "dead_lettered": len(dead)}


async def reaper_loop(interval_seconds: int = 60) -> None:
    """Background task para o main.py iniciar no startup.

    O try/except é obrigatório: uma exceção não tratada aqui mataria a task
    silenciosamente e o reaper simplesmente pararia de existir.
    """
    while True:
        try:
            await reap_orphan_jobs()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reaper falhou nesta iteração; segue no próximo ciclo.")
        await asyncio.sleep(interval_seconds)
