import json
from uuid import UUID
from app.core.database import get_pool
from app.domain.sample.entities import Project, ProjectAnalysis
from app.domain.shared.value_objects import MarkerType, ProjectCode


def _parse_jsonb(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value) if value else {}
    return dict(value)


class PgProjectRepository:
    async def get_all(self) -> list[Project]:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT p.*, u.name AS author_name, u.avatar_url AS author_avatar_url
                FROM projects p
                LEFT JOIN users u ON u.id = p.created_by
                ORDER BY p.created_at DESC
                """
            )
            project_ids = [r["id"] for r in rows]
            analyses_rows = []
            if project_ids:
                analyses_rows = await conn.fetch(
                    "SELECT * FROM project_analyses WHERE project_id = ANY($1::uuid[])",
                    project_ids,
                )
        analyses_by_project: dict[UUID, list[ProjectAnalysis]] = {}
        for ar in analyses_rows:
            pid = ar["project_id"]
            analyses_by_project.setdefault(pid, []).append(
                ProjectAnalysis(analysis_type=ar["analysis_type"], charts=list(ar["charts"]))
            )
        return [self._to_entity(r, analyses_by_project.get(r["id"], [])) for r in rows]

    async def get_by_id(self, project_id: UUID) -> Project | None:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT p.*, u.name AS author_name, u.avatar_url AS author_avatar_url
                FROM projects p
                LEFT JOIN users u ON u.id = p.created_by
                WHERE p.id = $1
                """,
                project_id,
            )
            if not row:
                return None
            analyses_rows = await conn.fetch(
                "SELECT * FROM project_analyses WHERE project_id = $1 ORDER BY created_at",
                project_id,
            )
        analyses = [
            ProjectAnalysis(analysis_type=ar["analysis_type"], charts=list(ar["charts"]))
            for ar in analyses_rows
        ]
        return self._to_entity(row, analyses)

    async def save(self, project: Project) -> None:
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO projects (id, code, name, description, marker_type, status, bioproject_accession, created_by, dada2_params)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (id) DO UPDATE
                        SET name                 = EXCLUDED.name,
                            description          = EXCLUDED.description,
                            status               = EXCLUDED.status,
                            bioproject_accession = EXCLUDED.bioproject_accession,
                            dada2_params         = EXCLUDED.dada2_params
                    """,
                    project.id, str(project.code), project.name,
                    project.description, project.marker_type.value, project.status,
                    project.bioproject_accession, project.created_by,
                    json.dumps(project.dada2_params or {}),
                )
                # Replace all analyses for this project
                await conn.execute(
                    "DELETE FROM project_analyses WHERE project_id = $1",
                    project.id,
                )
                for analysis in project.analyses:
                    await conn.execute(
                        """
                        INSERT INTO project_analyses (project_id, analysis_type, charts)
                        VALUES ($1, $2, $3)
                        """,
                        project.id, analysis.analysis_type, analysis.charts,
                    )

    def _to_entity(self, row, analyses: list[ProjectAnalysis]) -> Project:
        return Project(
            id=row["id"],
            code=ProjectCode(row["code"]),
            name=row["name"],
            description=row.get("description") or "",
            marker_type=MarkerType(row["marker_type"]),
            status=row["status"],
            bioproject_accession=row.get("bioproject_accession"),
            created_by=row.get("created_by"),
            author_name=row.get("author_name"),
            author_avatar_url=row.get("author_avatar_url"),
            analyses=analyses,
            dada2_params=_parse_jsonb(row.get("dada2_params")),
        )
