from fastapi import APIRouter
from app.core.database import get_pool

router = APIRouter()

# Tempos médios por tipo de análise (segundos) — baseado no CLAUDE.md
_ESTIMATED: dict[str, int] = {
    "deseq2":                 4 * 60,
    "ancombc2":               6 * 60,
    "maaslin2":               5 * 60,
    "spieceasi":             15 * 60,
    "random_forest":         12 * 60,
    "gsea":                   3 * 60,
    "funguild":               2 * 60,
    "picrust2":               5 * 60,
    "dada2_pipeline":        12 * 60,
    "metagenomics_pipeline":  6 * 60,
}
_DEFAULT_ESTIMATE = 10 * 60


@router.get("/status")
async def worker_status():
    pool = get_pool()
    async with pool.acquire() as conn:
        running_rows = await conn.fetch("""
            SELECT j.id, j.job_type, j.started_at, j.progress_pct, j.progress_stage,
                   p.code  AS project_code,
                   p.name  AS project_name,
                   EXTRACT(EPOCH FROM (NOW() - j.started_at))::int AS elapsed_s
            FROM pipeline_jobs j
            JOIN projects p ON p.id = j.project_id
            WHERE j.status = 'running'
            ORDER BY j.started_at
        """)

        queued_count = await conn.fetchval(
            "SELECT COUNT(*) FROM pipeline_jobs WHERE status = 'queued'"
        )

        recent_rows = await conn.fetch("""
            SELECT j.id, j.job_type, j.status, j.error_msg,
                   p.code AS project_code,
                   EXTRACT(EPOCH FROM (
                       NOW() - COALESCE(j.completed_at, j.started_at, j.created_at)
                   ))::int AS seconds_ago
            FROM pipeline_jobs j
            JOIN projects p ON p.id = j.project_id
            WHERE j.status IN ('done', 'failed')
            ORDER BY COALESCE(j.completed_at, j.created_at) DESC
            LIMIT 8
        """)

    running = []
    for r in running_rows:
        elapsed = r["elapsed_s"] or 0
        estimated = _ESTIMATED.get(r["job_type"], _DEFAULT_ESTIMATE)
        real_pct = r["progress_pct"] or 0
        # Progresso real reportado pelo worker tem prioridade; senão, estima por tempo
        if real_pct > 0:
            progress = min(real_pct, 99)
            remaining = max(int(estimated * (100 - progress) / 100), 0)
        else:
            progress = min(int(elapsed / estimated * 100), 95)
            remaining = max(estimated - elapsed, 0)
        running.append({
            "id":               str(r["id"]),
            "job_type":         r["job_type"],
            "project_code":     r["project_code"],
            "project_name":     r["project_name"],
            "elapsed_s":        elapsed,
            "estimated_s":      estimated,
            "progress_pct":     progress,
            "progress_stage":   r["progress_stage"],
            "remaining_s":      remaining,
        })

    recent = []
    for r in recent_rows:
        recent.append({
            "id":           str(r["id"]),
            "job_type":     r["job_type"],
            "status":       r["status"],
            "project_code": r["project_code"],
            "seconds_ago":  r["seconds_ago"] or 0,
            "error_msg":    r["error_msg"],
        })

    return {
        "running":      running,
        "queued_count": int(queued_count or 0),
        "recent":       recent,
    }
