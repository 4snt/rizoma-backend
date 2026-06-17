from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth_deps import get_current_user
from app.core.database import get_pool
from app.core.ncbi_entrez import list_sra_runs as ncbi_list_sra_runs
from app.domain.sample.entities import Project, ProjectAnalysis
from app.domain.shared.value_objects import MarkerType, ProjectCode
from app.infrastructure.repositories.pg_project_repo import PgProjectRepository

router = APIRouter()
repo = PgProjectRepository()


def _project_dict(p: Project) -> dict:
    return {
        "id":                   str(p.id),
        "code":                 p.code,
        "name":                 p.name,
        "description":          p.description,
        "marker_type":          p.marker_type,
        "status":               p.status,
        "bioproject_accession": p.bioproject_accession,
        "created_by":           str(p.created_by) if p.created_by else None,
        "dada2_params":         p.dada2_params or {},
        "author": {
            "name":       p.author_name,
            "avatar_url": p.author_avatar_url,
        } if p.author_name else None,
        "analyses": [
            {"analysis_type": a.analysis_type, "charts": a.charts}
            for a in p.analyses
        ],
    }


class AnalysisConfig(BaseModel):
    analysis_type: str
    charts: list[str] = []


class CreateProjectRequest(BaseModel):
    code: str
    name: str
    description: str = ""
    marker_type: MarkerType
    analyses: list[AnalysisConfig] = []
    dada2_params: dict = {}


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    analyses: list[AnalysisConfig] | None = None
    dada2_params: dict | None = None


@router.get("/")
async def list_projects():
    projects = await repo.get_all()
    return [_project_dict(p) for p in projects]


@router.get("/{project_id}")
async def get_project(project_id: UUID):
    project = await repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    return _project_dict(project)


@router.get("/{project_id}/sra-runs")
async def list_project_sra_runs(project_id: UUID):
    """Lista SRR runs do BioProject associado ao projeto."""
    project = await repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    if not project.bioproject_accession:
        return {"bioproject": None, "runs": []}
    try:
        runs = await ncbi_list_sra_runs(project.bioproject_accession)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao consultar NCBI: {e}")
    return {"bioproject": project.bioproject_accession, "runs": runs}


@router.post("/", status_code=201)
async def create_project(
    body: CreateProjectRequest,
    user: dict = Depends(get_current_user),
):
    project = Project(
        code=ProjectCode(body.code),
        name=body.name,
        description=body.description,
        marker_type=body.marker_type,
        created_by=UUID(user["user_id"]),
        analyses=[
            ProjectAnalysis(analysis_type=a.analysis_type, charts=a.charts)
            for a in body.analyses
        ],
        dada2_params=body.dada2_params or {},
    )
    await repo.save(project)
    return {"id": str(project.id)}


def _assert_can_edit(project: Project, user: dict) -> None:
    """Admin ou criador do projeto podem editar/excluir."""
    is_admin = user.get("role") == "admin"
    is_owner = project.created_by is not None and str(project.created_by) == user["user_id"]
    if not (is_admin or is_owner):
        raise HTTPException(
            status_code=403,
            detail="Apenas o administrador ou o criador do projeto podem fazer isso.",
        )


@router.put("/{project_id}")
async def update_project(
    project_id: UUID,
    body: UpdateProjectRequest,
    user: dict = Depends(get_current_user),
):
    project = await repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    _assert_can_edit(project, user)

    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.analyses is not None:
        project.analyses = [
            ProjectAnalysis(analysis_type=a.analysis_type, charts=a.charts)
            for a in body.analyses
        ]
    if body.dada2_params is not None:
        project.dada2_params = body.dada2_params

    await repo.save(project)
    return _project_dict(project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: UUID,
    user: dict = Depends(get_current_user),
):
    """
    Remove um projeto e todos os seus dados associados.

    FKs de samples/pipeline_jobs não têm ON DELETE CASCADE, então a deleção é feita
    na ordem correta dentro de uma transação. Os large objects (FASTQs e phyloseq)
    são desvinculados automaticamente pelos triggers lo_manage (migration 005);
    apenas result_oid de analysis_results precisa de lo_unlink manual.
    """
    project = await repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    _assert_can_edit(project, user)

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            job_ids = [
                r["id"]
                for r in await conn.fetch(
                    "SELECT id FROM pipeline_jobs WHERE project_id = $1", project_id
                )
            ]
            if job_ids:
                # analysis_results não tem trigger lo_manage: desvincula LOs manualmente
                await conn.execute(
                    """
                    SELECT lo_unlink(result_oid)
                    FROM analysis_results
                    WHERE job_id = ANY($1::uuid[]) AND result_oid IS NOT NULL
                    """,
                    job_ids,
                )
                await conn.execute(
                    "DELETE FROM analysis_results WHERE job_id = ANY($1::uuid[])", job_ids
                )
                await conn.execute(
                    "DELETE FROM network_edges WHERE job_id = ANY($1::uuid[])", job_ids
                )
            # trigger lo_cleanup_jobs desvincula phyloseq_oid
            await conn.execute(
                "DELETE FROM pipeline_jobs WHERE project_id = $1", project_id
            )
            # triggers lo_cleanup_samples_r1/r2 desvinculam os FASTQs
            await conn.execute("DELETE FROM samples WHERE project_id = $1", project_id)
            # project_analyses cascateia (migration 004)
            await conn.execute("DELETE FROM projects WHERE id = $1", project_id)
