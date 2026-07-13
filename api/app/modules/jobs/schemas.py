"""Contratos da fila de jobs."""
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EnqueueRequest(BaseModel):
    project_id: UUID
    job_type: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 100


class JobOut(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID
    job_type: str
    status: str
    priority: int
    attempts: int
    max_attempts: int
    payload: dict[str, Any]
    progress_pct: int
    progress_stage: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    next_retry_at: datetime | None
    heartbeat_at: datetime | None
    worker_id: str | None
    error_code: str | None
    error_message: str | None
    result_summary: dict[str, Any] | None
    created_by: UUID | None
    created_at: datetime


class AnalysisResultOut(BaseModel):
    id: UUID
    job_id: UUID
    analysis_type: str
    result_data: dict[str, Any]
    created_at: datetime


class JobDetailOut(JobOut):
    results: list[AnalysisResultOut] = Field(default_factory=list)


# ── Worker ──────────────────────────────────────────────────────────────
class DequeueRequest(BaseModel):
    worker_id: str = "worker-1"


class HeartbeatRequest(BaseModel):
    progress_pct: int | None = Field(default=None, ge=0, le=100)
    progress_stage: str | None = None


class CompleteRequest(BaseModel):
    analysis_type: str
    result_data: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] | None = None


class FailRequest(BaseModel):
    error_code: str | None = None
    error_message: str
