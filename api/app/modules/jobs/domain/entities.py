"""Entidades da fila de jobs: Job e AnalysisResult.

O backoff exponencial e a decisão retry-vs-dead-letter são regra de domínio
pura (nenhum I/O) — vivem aqui, não espalhadas dentro do `service.py`.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.modules.jobs.domain.exceptions import JobRunningError, NotCancellableError

# Categorias que o worker precisa BAIXAR para trabalhar. Um FASTQ não mora no
# banco: o worker recebe uma URL assinada interna e lê direto do MinIO.
WORKER_INPUT_CATEGORIES = ("fastq_r1", "fastq_r2", "phyloseq")

_CANCELLABLE_STATUSES = ("queued", "retry_scheduled")


def backoff(attempts: int) -> timedelta:
    """Backoff exponencial: 2^attempts minutos, teto de 1h. Retentar de
    imediato um worker que acabou de cair só derruba o próximo."""
    minutes = min(2 ** max(attempts, 0), 60)
    return timedelta(minutes=minutes)


@dataclass
class RetryDecision:
    """O que fazer com um job que falhou: tentar de novo, ou desistir."""

    status: str  # "retry_scheduled" | "dead_letter"
    next_retry_at: datetime | None
    error_code: str | None
    error_message: str | None


def assert_cancellable(job_status: str) -> None:
    """Um job em `running` não pode ser cancelado pela API — não há como matar
    o processo do worker a partir daqui, e prometer que cancelou seria
    mentira. Fora de `queued`/`retry_scheduled`, o job já terminou."""
    if job_status == "running":
        raise JobRunningError(
            "Job já está em execução — não pode ser cancelado pela API."
        )
    if job_status not in _CANCELLABLE_STATUSES:
        raise NotCancellableError(f"Job em estado '{job_status}' não pode ser cancelado.")


def resolve_failure(
    *, attempts: int, max_attempts: int, error_code: str | None, error_message: str | None
) -> RetryDecision:
    """Esgotou as tentativas: sai da fila e vira caso para humano
    (`dead_letter`). Senão, agenda a próxima tentativa com backoff."""
    if attempts < max_attempts:
        return RetryDecision(
            status="retry_scheduled",
            next_retry_at=datetime.now(timezone.utc) + backoff(attempts),
            error_code=error_code,
            error_message=error_message,
        )
    return RetryDecision(
        status="dead_letter", next_retry_at=None, error_code=error_code, error_message=error_message
    )


@dataclass
class AnalysisResult:
    id: UUID
    organization_id: UUID
    job_id: UUID
    analysis_type: str
    result_data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "analysis_type": self.analysis_type,
            "result_data": self.result_data,
            "created_at": self.created_at,
        }


@dataclass
class Job:
    id: UUID
    organization_id: UUID
    project_id: UUID
    job_type: str
    status: str
    priority: int
    attempts: int
    max_attempts: int
    payload: dict[str, Any] = field(default_factory=dict)
    progress_pct: int = 0
    progress_stage: str | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    next_retry_at: datetime | None = None
    heartbeat_at: datetime | None = None
    worker_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    result_summary: dict[str, Any] | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None

    def assert_can_be_cancelled(self) -> None:
        assert_cancellable(self.status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "project_id": self.project_id,
            "job_type": self.job_type,
            "status": self.status,
            "priority": self.priority,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "payload": self.payload,
            "progress_pct": self.progress_pct,
            "progress_stage": self.progress_stage,
            "queued_at": self.queued_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "next_retry_at": self.next_retry_at,
            "heartbeat_at": self.heartbeat_at,
            "worker_id": self.worker_id,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "result_summary": self.result_summary,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }
