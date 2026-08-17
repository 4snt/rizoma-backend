"""Persistência de resultados de laboratório. Todo `sqlalchemy.text()` do
módulo mora aqui — `service.py` só orquestra entidades.
"""
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.laboratory.domain.entities import LabResult, ResultVersion

_VERSION_COLS = """
    id, organization_id, result_id, version, value_numeric, value_text, unit, lod, loq,
    uncertainty, below_lod, status, supersedes, change_reason,
    created_by, reviewed_by, created_at
"""


def _version_from_row(row: dict[str, Any]) -> ResultVersion:
    return ResultVersion(
        id=row["id"],
        organization_id=row.get("organization_id"),
        result_id=row["result_id"],
        version=row["version"],
        value_numeric=row["value_numeric"],
        value_text=row["value_text"],
        unit=row["unit"],
        lod=row["lod"],
        loq=row["loq"],
        uncertainty=row["uncertainty"],
        below_lod=row["below_lod"],
        status=row["status"],
        supersedes=row["supersedes"],
        change_reason=row["change_reason"],
        created_by=row["created_by"],
        reviewed_by=row["reviewed_by"],
        created_at=row["created_at"],
    )


class PgLabResultRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def sample_exists(self, sample_id: UUID) -> bool:
        res = await self.session.execute(
            text("SELECT 1 FROM samples WHERE id = :i"), {"i": str(sample_id)}
        )
        return res.first() is not None

    async def create_header(
        self, *, id: UUID, organization_id: UUID, sample_id: UUID, analyte: str, method: str | None
    ) -> None:
        await self.session.execute(
            text(
                "INSERT INTO lab_results (id, organization_id, sample_id, analyte, method) "
                "VALUES (:i, :o, :s, :a, :m)"
            ),
            {
                "i": str(id),
                "o": str(organization_id),
                "s": str(sample_id),
                "a": analyte,
                "m": method,
            },
        )

    async def append_version(self, version: ResultVersion) -> None:
        """`result_versions` é append-only por trigger no banco — este método
        só insere."""
        await self.session.execute(
            text(
                """
                INSERT INTO result_versions (
                    id, organization_id, result_id, version, value_numeric, value_text,
                    unit, lod, loq, uncertainty, below_lod, status, supersedes,
                    change_reason, created_by, reviewed_by
                ) VALUES (
                    :i, :o, :r, :v, :vn, :vt, :u, :lod, :loq, :unc, :below, :st,
                    :sup, :reason, :cb, :rb
                )
                """
            ),
            {
                "i": str(version.id),
                "o": str(version.organization_id),
                "r": str(version.result_id),
                "v": version.version,
                "vn": version.value_numeric,
                "vt": version.value_text,
                "u": version.unit,
                "lod": version.lod,
                "loq": version.loq,
                "unc": version.uncertainty,
                "below": version.below_lod,
                "st": version.status,
                "sup": str(version.supersedes) if version.supersedes else None,
                "reason": version.change_reason,
                "cb": str(version.created_by),
                "rb": str(version.reviewed_by) if version.reviewed_by else None,
            },
        )

    async def get_header(self, result_id: UUID):
        res = await self.session.execute(
            text(
                "SELECT id, sample_id, analyte, method, created_at "
                "FROM lab_results WHERE id = :i"
            ),
            {"i": str(result_id)},
        )
        return res.mappings().first()

    async def get(self, result_id: UUID) -> LabResult | None:
        header = await self.get_header(result_id)
        if header is None:
            return None
        res = await self.session.execute(
            text(f"SELECT {_VERSION_COLS} FROM result_versions WHERE result_id = :r ORDER BY version"),
            {"r": str(result_id)},
        )
        versions = [_version_from_row(dict(r)) for r in res.mappings().all()]
        return LabResult(
            id=header["id"],
            organization_id=versions[0].organization_id if versions else None,
            sample_id=header["sample_id"],
            analyte=header["analyte"],
            method=header["method"],
            created_at=header["created_at"],
            versions=versions,
        )

    async def latest_version(self, result_id: UUID) -> ResultVersion | None:
        """A versão corrente é a de maior `version` — nunca "a última
        editada", porque editar não existe aqui."""
        res = await self.session.execute(
            text(
                f"SELECT {_VERSION_COLS} FROM result_versions "
                "WHERE result_id = :r ORDER BY version DESC LIMIT 1"
            ),
            {"r": str(result_id)},
        )
        row = res.mappings().first()
        return _version_from_row(dict(row)) if row is not None else None

    async def list_ids_by_sample(self, sample_id: UUID) -> list[UUID]:
        res = await self.session.execute(
            text("SELECT id FROM lab_results WHERE sample_id = :s ORDER BY created_at"),
            {"s": str(sample_id)},
        )
        return [r["id"] for r in res.mappings().all()]

    async def list_all(
        self, project_id: UUID | None, sample_id: UUID | None
    ) -> list[dict[str, Any]]:
        """Resultados da organização inteira, com a versão CORRENTE apenas
        (histórico completo continua só em `get()`, que é o detalhe da
        amostra). `project_id`/`sample_id` são filtro opcional, não
        pré-requisito — mesma decisão de `lims.list_all` e
        `reports.list_all`: projeto (e amostra) viram agregador, não dono.

        Uma query só: `lab_results` join `samples`/`projects` pro código
        exibido, join LATERAL pra pegar só a versão de maior número por
        resultado (sem N+1 por amostra no frontend).
        """
        res = await self.session.execute(
            text(
                """
                SELECT
                    lr.id, lr.sample_id, lr.analyte, lr.method, lr.created_at,
                    s.code AS sample_code, s.project_id AS project_id,
                    p.code AS project_code,
                    rv.id AS version_id, rv.organization_id AS version_organization_id,
                    rv.version, rv.value_numeric, rv.value_text, rv.unit,
                    rv.lod, rv.loq, rv.uncertainty, rv.below_lod, rv.status,
                    rv.supersedes, rv.change_reason, rv.created_by, rv.reviewed_by,
                    rv.created_at AS version_created_at
                FROM lab_results lr
                JOIN samples s ON s.id = lr.sample_id
                JOIN projects p ON p.id = s.project_id
                JOIN LATERAL (
                    SELECT * FROM result_versions
                    WHERE result_id = lr.id ORDER BY version DESC LIMIT 1
                ) rv ON true
                WHERE (CAST(:project_id AS uuid) IS NULL OR s.project_id = :project_id)
                  AND (CAST(:sample_id AS uuid) IS NULL OR lr.sample_id = :sample_id)
                ORDER BY lr.created_at DESC
                """
            ),
            {
                "project_id": str(project_id) if project_id else None,
                "sample_id": str(sample_id) if sample_id else None,
            },
        )
        return [dict(r) for r in res.mappings().all()]
