import json
from uuid import UUID
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel
from app.infrastructure.repositories.pg_job_repo import PgJobRepository
from app.domain.pipeline.entities import PipelineJob

router = APIRouter()
repo = PgJobRepository()

VALID_JOB_TYPES = {
    "deseq2", "ancombc2", "maaslin2", "spieceasi",
    "random_forest", "gsea", "funguild", "picrust2",
    "dada2_pipeline",          # gera phyloseq .rds a partir dos FASTQs do projeto
    "metagenomics_pipeline",   # vegan + ANCOM-BC sobre um phyloseq existente
}


class EnqueueRequest(BaseModel):
    project_id: UUID
    job_type: str
    payload: dict = {}
    phyloseq_oid: int | None = None


@router.post("/enqueue")
async def enqueue_job(body: EnqueueRequest):
    if body.job_type not in VALID_JOB_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"job_type inválido. Valores aceitos: {sorted(VALID_JOB_TYPES)}",
        )

    job = PipelineJob(
        project_id=body.project_id,
        job_type=body.job_type,
        payload=body.payload,
        phyloseq_oid=body.phyloseq_oid,
    )

    try:
        await repo.enqueue(job)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao enfileirar job: {e}")

    return {
        "job_id": str(job.id),
        "job_type": job.job_type,
        "status": job.status.value,
    }


@router.get("/{project_id}")
async def list_jobs(project_id: UUID):
    jobs = await repo.list_by_project(project_id)
    result = []
    for j in jobs:
        row = {}
        for k, v in j.items():
            if hasattr(v, 'isoformat'):
                row[k] = v.isoformat()
            elif isinstance(v, (int, float, bool, type(None))):
                row[k] = v
            else:
                row[k] = str(v)
        result.append(row)
    return result


@router.websocket("/ws/status")
async def job_status_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            # Echo de status — implementar LISTEN/NOTIFY aqui
            await websocket.send_text(f"ack:{data}")
    except WebSocketDisconnect:
        pass
