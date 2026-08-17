"""Persistência do agregado Laudo. Todo `sqlalchemy.text()` sobre a tabela
`reports` mora aqui — `service.py` só orquestra entidade + repository.
"""
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reports.domain.entities import Report

_COLS = (
    "id, organization_id, project_id, code, version, title, status, content, "
    "storage_key, sha256, signed_by, signed_at, created_by, created_at"
)


def _from_row(row: dict[str, Any]) -> Report:
    return Report(
        id=row["id"],
        organization_id=row["organization_id"],
        project_id=row["project_id"],
        code=row["code"],
        version=row["version"],
        title=row["title"],
        status=row["status"],
        content=row["content"],
        storage_key=row["storage_key"],
        sha256=row["sha256"],
        signed_by=row["signed_by"],
        signed_at=row["signed_at"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


class PgReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_version_for_code(self, code: str) -> int:
        """UNIQUE(organization_id, code, version): reemitir com o mesmo
        código gera a versão seguinte em vez de estourar conflito."""
        res = await self.session.execute(
            text("SELECT COALESCE(MAX(version), 0) + 1 FROM reports WHERE code = :c"),
            {"c": code},
        )
        return res.scalar_one()

    async def create(self, report: Report) -> Report:
        await self.session.execute(
            text(
                """
                INSERT INTO reports (
                    id, organization_id, project_id, code, version, title, status,
                    content, created_by
                ) VALUES (
                    :i, :o, :p, :c, :v, :t, :st, CAST(:content AS jsonb), :cb
                )
                """
            ),
            {
                "i": str(report.id),
                "o": str(report.organization_id),
                "p": str(report.project_id),
                "c": report.code,
                "v": report.version,
                "t": report.title,
                "st": report.status,
                "content": json.dumps(report.content, ensure_ascii=False),
                "cb": str(report.created_by),
            },
        )
        return report

    async def get(self, report_id: UUID) -> Report | None:
        res = await self.session.execute(
            text(f"SELECT {_COLS} FROM reports WHERE id = :i"), {"i": str(report_id)}
        )
        row = res.mappings().first()
        return _from_row(dict(row)) if row is not None else None

    async def list_by_project(self, project_id: UUID) -> list[Report]:
        res = await self.session.execute(
            text(f"SELECT {_COLS} FROM reports WHERE project_id = :p ORDER BY created_at DESC"),
            {"p": str(project_id)},
        )
        return [_from_row(dict(r)) for r in res.mappings().all()]

    async def list_all(self, project_id: UUID | None) -> list[dict[str, Any]]:
        """Laudos da organização inteira, `project_id` só como filtro
        opcional — mesma decisão de `lims.list_all`/`laboratory.list_all`:
        projeto é agregador, não pré-requisito de rota. Uma query só, join
        com `projects` pro código/nome exibido; RLS isola por organização."""
        res = await self.session.execute(
            text(
                f"""
                SELECT {', '.join(f'r.{c.strip()}' for c in _COLS.split(','))},
                       p.code AS project_code, p.name AS project_name
                FROM reports r
                JOIN projects p ON p.id = r.project_id
                WHERE (CAST(:project_id AS uuid) IS NULL OR r.project_id = :project_id)
                ORDER BY r.created_at DESC
                """
            ),
            {"project_id": str(project_id) if project_id else None},
        )
        return [dict(r) for r in res.mappings().all()]

    async def sign(
        self,
        report_id: UUID,
        *,
        content: dict[str, Any],
        storage_key: str,
        sha256: str,
        signed_by: UUID,
        signed_at,
    ) -> Report:
        await self.session.execute(
            text(
                """
                UPDATE reports SET
                    content = CAST(:content AS jsonb),
                    storage_key = :k,
                    sha256 = :h,
                    signed_by = :sb,
                    signed_at = :sa,
                    status = 'published'
                WHERE id = :i
                """
            ),
            {
                "content": json.dumps(content, ensure_ascii=False),
                "k": storage_key,
                "h": sha256,
                "sb": str(signed_by),
                "sa": signed_at,
                "i": str(report_id),
            },
        )
        report = await self.get(report_id)
        assert report is not None
        return report
