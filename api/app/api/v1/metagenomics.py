import json
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.core.database import get_pool

router = APIRouter()

TaxLevel = Literal["domain", "phylum", "class", "order", "family", "genus", "species"]
BetaMetric = Literal["bray", "jaccard", "unifrac"]


def _parse_result(row) -> dict:
    if row is None:
        return {}
    v = row["result_data"]
    if isinstance(v, str):
        return json.loads(v)
    return dict(v) if v else {}


async def _latest_result(conn, project_id: UUID, analysis_type: str):
    return await conn.fetchrow(
        """
        SELECT ar.result_data
        FROM analysis_results ar
        JOIN pipeline_jobs pj ON pj.id = ar.job_id
        WHERE pj.project_id = $1
          AND pj.job_type = 'metagenomics_pipeline'
          AND pj.status = 'done'
          AND ar.analysis_type = $2
        ORDER BY pj.completed_at DESC
        LIMIT 1
        """,
        project_id,
        analysis_type,
    )


@router.get("/{project_id}/status")
async def get_status(project_id: UUID):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, status, created_at, completed_at, error_msg
            FROM pipeline_jobs
            WHERE project_id = $1 AND job_type = 'metagenomics_pipeline'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            project_id,
        )
    if not row:
        return {"has_results": False, "job_status": None, "last_job_id": None}
    r = dict(row)
    return {
        "has_results": r["status"] == "done",
        "job_status": r["status"],
        "last_job_id": str(r["id"]),
        "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
        "error_msg": r["error_msg"],
    }


class RunRequest(BaseModel):
    phyloseq_oid: int


@router.post("/{project_id}/run", status_code=202)
async def run_pipeline(project_id: UUID, body: RunRequest):
    """Enfileira job metagenomics_pipeline (SILVA → vegan → ANCOM-BC)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        proj = await conn.fetchrow("SELECT id FROM projects WHERE id = $1", project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Projeto não encontrado")
        row = await conn.fetchrow(
            """
            INSERT INTO pipeline_jobs (project_id, job_type, status, payload, phyloseq_oid)
            VALUES ($1, 'metagenomics_pipeline', 'queued', '{}', $2)
            RETURNING id
            """,
            project_id,
            body.phyloseq_oid,
        )
    return {"job_id": str(row["id"])}


@router.get("/{project_id}/asv-table")
async def get_asv_table(
    project_id: UUID,
    level: TaxLevel = Query("genus"),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await _latest_result(conn, project_id, "asv_table")
    if not row:
        raise HTTPException(status_code=404, detail="Nenhuma análise metagenômica concluída")

    data = _parse_result(row)
    rows = data.get("rows", [])
    sample_names = data.get("sample_names", [])

    # Aggregate by requested level
    aggregated: dict[str, dict] = {}
    for r in rows:
        tax = r.get("taxonomy") or {}
        key = tax.get(level) or tax.get("genus") or r.get("taxon", "Unknown")
        if not key or key in ("NA", "None", ""):
            key = "Unclassified"
        if key not in aggregated:
            aggregated[key] = {
                "taxon": key,
                "taxonomy": tax,
                "samples": {s: 0 for s in sample_names},
                "total": 0,
            }
        for s in sample_names:
            v = r.get("samples", {}).get(s, 0) or 0
            aggregated[key]["samples"][s] += v
            aggregated[key]["total"] += v

    result_rows = sorted(aggregated.values(), key=lambda x: -x["total"])
    return {
        "level": level,
        "sample_names": sample_names,
        "rows": result_rows,
        "available_levels": data.get("available_levels", ["phylum", "class", "order", "family", "genus"]),
        "total_asvs": len(rows),
    }


@router.get("/{project_id}/asv-table/full")
async def get_asv_table_full(project_id: UUID):
    """Tabela com todos os níveis taxonômicos como colunas + contagens e abundância relativa (%) por amostra."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await _latest_result(conn, project_id, "asv_table")
    if not row:
        raise HTTPException(status_code=404, detail="Nenhuma análise metagenômica concluída")

    data = _parse_result(row)
    rows = data.get("rows", [])
    sample_names = data.get("sample_names", [])

    TAX_LEVELS = ["domain", "phylum", "class", "order", "family", "genus", "species"]

    # Per-sample totals (from raw ASV rows)
    sample_totals: dict[str, float] = {s: 0.0 for s in sample_names}
    for r in rows:
        for s in sample_names:
            sample_totals[s] += float((r.get("samples") or {}).get(s, 0) or 0)

    # Aggregate ASVs sharing the same full lineage path
    aggregated: dict[str, dict] = {}
    for r in rows:
        tax = r.get("taxonomy") or {}
        lineage = {lvl: (tax.get(lvl) or "Unclassified") for lvl in TAX_LEVELS}
        key = "|".join(lineage.values())

        if key not in aggregated:
            aggregated[key] = {**lineage, "samples": {s: 0 for s in sample_names}, "total": 0}

        for s in sample_names:
            count = int((r.get("samples") or {}).get(s, 0) or 0)
            aggregated[key]["samples"][s] += count
            aggregated[key]["total"] += count

    result_rows = []
    for lin in sorted(aggregated.values(), key=lambda x: -x["total"]):
        rel_ab = {
            s: round(lin["samples"][s] / sample_totals[s] * 100, 4)
            if sample_totals.get(s, 0) > 0 else 0.0
            for s in sample_names
        }
        result_rows.append({**lin, "rel_abundance": rel_ab})

    return {
        "tax_levels": TAX_LEVELS,
        "sample_names": sample_names,
        "rows": result_rows,
        "total_asvs": len(rows),
    }


@router.get("/{project_id}/diversity")
async def get_diversity(
    project_id: UUID,
    level: TaxLevel = Query("genus"),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await _latest_result(conn, project_id, "diversity")
    if not row:
        raise HTTPException(status_code=404, detail="Nenhuma análise de diversidade concluída")
    return _parse_result(row)


@router.get("/{project_id}/ordination")
async def get_ordination(
    project_id: UUID,
    type: Literal["pcoa", "pca"] = Query("pcoa"),
    beta_metric: BetaMetric = Query("bray"),
    level: TaxLevel = Query("genus"),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await _latest_result(conn, project_id, "ordination")
    if not row:
        raise HTTPException(status_code=404, detail="Nenhuma análise de ordenação concluída")

    data = _parse_result(row)
    ordinations = data if isinstance(data, list) else [data]
    for o in ordinations:
        if o.get("beta_metric") == beta_metric and o.get("type") == type:
            return o
    return ordinations[0] if ordinations else {}


@router.get("/{project_id}/biomarkers")
async def get_biomarkers(
    project_id: UUID,
    level: TaxLevel = Query("genus"),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await _latest_result(conn, project_id, "biomarkers")
    if not row:
        raise HTTPException(status_code=404, detail="Nenhuma análise de biomarcadores concluída")
    return _parse_result(row)
