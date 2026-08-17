"""Persistência do LIMS. Todo `sqlalchemy.text()` do módulo mora aqui — o
`service.py` não fala SQL, só entidades.

Recebe a `AsyncSession` já aberta pelo `Ctx` (não abre conexão própria como o
`get_pool()` do v1): a RLS depende do `SET LOCAL app.organization_id` já
aplicado nessa sessão pelo `shared/context.py`, então o repository herda o
isolamento de graça, sem precisar repetir `WHERE organization_id = ...`.
"""
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.lims.domain.entities import CustodyEvent, Project, Sample
from app.modules.lims.domain.exceptions import DuplicateError
from app.modules.lims.domain.value_objects import GeoPoint

_SAMPLE_COLS = """
    id, organization_id, project_id, code, matrix, treatment_group, replicate,
    status, collected_by, occurred_at, recorded_at, notes, created_at,
    ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon
"""

_CUSTODY_COLS = """
    id, organization_id, sample_id, seq, event_type, from_custodian, to_custodian,
    occurred_at, recorded_at, temperature_c, condition, notes, prev_hash, hash
"""

_GEOM_SQL = (
    "CASE WHEN CAST(:lat AS double precision) IS NULL "
    "  OR CAST(:lon AS double precision) IS NULL THEN NULL "
    "ELSE ST_SetSRID(ST_MakePoint("
    "  CAST(:lon AS double precision), CAST(:lat AS double precision)), 4326)::geography END"
)


def _geo_params(geo: GeoPoint | None) -> dict[str, float | None]:
    return {"lat": geo.lat if geo else None, "lon": geo.lon if geo else None}


def _project_from_row(row: dict[str, Any]) -> Project:
    return Project(
        id=row["id"],
        organization_id=row["organization_id"],
        code=row["code"],
        name=row["name"],
        description=row["description"],
        customer_user_id=row["customer_user_id"],
        marker_type=row["marker_type"],
        status=row["status"],
        dada2_params=row["dada2_params"] or {},
        analyses=row["analyses"] or [],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def _sample_from_row(row: dict[str, Any]) -> Sample:
    return Sample(
        id=row["id"],
        organization_id=row["organization_id"],
        project_id=row["project_id"],
        code=row["code"],
        matrix=row["matrix"],
        status=row["status"],
        treatment_group=row["treatment_group"],
        replicate=row["replicate"],
        geo=GeoPoint.from_optional(row.get("lat"), row.get("lon")),
        collected_by=row["collected_by"],
        occurred_at=row["occurred_at"],
        recorded_at=row["recorded_at"],
        notes=row["notes"],
        created_at=row["created_at"],
    )


def _custody_from_row(row: dict[str, Any]) -> CustodyEvent:
    return CustodyEvent(
        id=row["id"],
        organization_id=row["organization_id"],
        sample_id=row["sample_id"],
        seq=row["seq"],
        event_type=row["event_type"],
        from_custodian=row["from_custodian"],
        to_custodian=row["to_custodian"],
        occurred_at=row["occurred_at"],
        prev_hash=row["prev_hash"],
        hash=row["hash"],
        temperature_c=row["temperature_c"],
        condition=row["condition"],
        notes=row["notes"],
        recorded_at=row["recorded_at"],
    )


class PgProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def customer_is_member(self, organization_id: UUID, user_id: UUID) -> bool:
        """O 'cliente' de um projeto agora é sempre um membro real da
        organização — sem isso, `customer_user_id` poderia apontar pra
        qualquer usuário do sistema, de qualquer org."""
        row = (
            await self.session.execute(
                text(
                    "SELECT 1 FROM organization_members "
                    "WHERE organization_id = :o AND user_id = :u"
                ),
                {"o": str(organization_id), "u": str(user_id)},
            )
        ).first()
        return row is not None

    async def create(self, project: Project) -> Project:
        try:
            res = await self.session.execute(
                text(
                    """
                    INSERT INTO projects
                        (id, organization_id, customer_user_id, code, name, description,
                         marker_type, dada2_params, analyses, created_by)
                    VALUES (:id, :org, :customer, :code, :name, :description,
                            :marker, CAST(:dada2 AS jsonb), CAST(:analyses AS jsonb), :user)
                    RETURNING *
                    """
                ),
                {
                    "id": str(project.id),
                    "org": str(project.organization_id),
                    "customer": str(project.customer_user_id) if project.customer_user_id else None,
                    "code": project.code,
                    "name": project.name,
                    "description": project.description,
                    "marker": project.marker_type,
                    "dada2": json.dumps(project.dada2_params),
                    "analyses": json.dumps(project.analyses),
                    "user": str(project.created_by) if project.created_by else None,
                },
            )
        except IntegrityError as exc:
            raise DuplicateError(
                f"Já existe um projeto com o código '{project.code}' nesta organização."
            ) from exc
        return _project_from_row(dict(res.mappings().first()))

    async def list_all(self) -> list[Project]:
        res = await self.session.execute(text("SELECT * FROM projects ORDER BY created_at"))
        return [_project_from_row(dict(r)) for r in res.mappings().all()]

    async def get(self, project_id: UUID) -> Project | None:
        res = await self.session.execute(
            text("SELECT * FROM projects WHERE id = :id"), {"id": str(project_id)}
        )
        row = res.mappings().first()
        return _project_from_row(dict(row)) if row is not None else None

    async def update_status(self, project_id: UUID, new_status: str) -> Project | None:
        res = await self.session.execute(
            text("UPDATE projects SET status = :s WHERE id = :id RETURNING *"),
            {"s": new_status, "id": str(project_id)},
        )
        row = res.mappings().first()
        return _project_from_row(dict(row)) if row is not None else None


class PgSampleRepository:
    """Amostra e cadeia de custódia são o mesmo agregado: `transition` grava as
    duas na mesma transação, e é assim que este repository as trata."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, sample: Sample) -> Sample:
        try:
            res = await self.session.execute(
                text(
                    f"""
                    INSERT INTO samples
                        (id, organization_id, project_id, code, matrix, treatment_group,
                         replicate, status, geom, collected_by, occurred_at, notes)
                    VALUES (:id, :org, :project, :code, :matrix, :group, :replicate,
                            :status, {_GEOM_SQL}, :user, :occurred_at, :notes)
                    RETURNING {_SAMPLE_COLS}
                    """
                ),
                {
                    "id": str(sample.id),
                    "org": str(sample.organization_id),
                    "project": str(sample.project_id),
                    "code": sample.code,
                    "matrix": sample.matrix,
                    "group": sample.treatment_group,
                    "replicate": sample.replicate,
                    "status": sample.status,
                    **_geo_params(sample.geo),
                    "user": str(sample.collected_by) if sample.collected_by else None,
                    "occurred_at": sample.occurred_at,
                    "notes": sample.notes,
                },
            )
        except IntegrityError as exc:
            raise DuplicateError(
                f"Já existe uma amostra com o código '{sample.code}' neste projeto."
            ) from exc
        return _sample_from_row(dict(res.mappings().first()))

    async def list_by_project(self, project_id: UUID) -> list[Sample]:
        res = await self.session.execute(
            text(f"SELECT {_SAMPLE_COLS} FROM samples WHERE project_id = :p ORDER BY code"),
            {"p": str(project_id)},
        )
        return [_sample_from_row(dict(r)) for r in res.mappings().all()]

    async def get(self, sample_id: UUID) -> Sample | None:
        res = await self.session.execute(
            text(f"SELECT {_SAMPLE_COLS} FROM samples WHERE id = :id"),
            {"id": str(sample_id)},
        )
        row = res.mappings().first()
        return _sample_from_row(dict(row)) if row is not None else None

    async def get_for_update(self, sample_id: UUID) -> Sample | None:
        """`FOR UPDATE` serializa duas transições concorrentes da mesma
        amostra: sem o lock, ambas leriam o mesmo `seq` máximo da cadeia de
        custódia e uma quebraria o `UNIQUE (sample_id, seq)` — ou pior,
        gravaria dois ramos com o mesmo `prev_hash`."""
        res = await self.session.execute(
            text(f"SELECT {_SAMPLE_COLS} FROM samples WHERE id = :id FOR UPDATE"),
            {"id": str(sample_id)},
        )
        row = res.mappings().first()
        return _sample_from_row(dict(row)) if row is not None else None

    async def update_status(self, sample_id: UUID, new_status: str) -> Sample | None:
        res = await self.session.execute(
            text(f"UPDATE samples SET status = :s WHERE id = :id RETURNING {_SAMPLE_COLS}"),
            {"s": new_status, "id": str(sample_id)},
        )
        row = res.mappings().first()
        return _sample_from_row(dict(row)) if row is not None else None

    async def last_custody_event(self, sample_id: UUID) -> CustodyEvent | None:
        res = await self.session.execute(
            text(
                f"SELECT {_CUSTODY_COLS} FROM custody_events "
                "WHERE sample_id = :s ORDER BY seq DESC LIMIT 1"
            ),
            {"s": str(sample_id)},
        )
        row = res.mappings().first()
        return _custody_from_row(dict(row)) if row is not None else None

    async def append_custody_event(self, event: CustodyEvent) -> None:
        """A tabela é append-only por trigger no banco — este método só
        insere; o próprio Postgres recusa `UPDATE`/`DELETE`."""
        await self.session.execute(
            text(
                f"""
                INSERT INTO custody_events
                    (id, organization_id, sample_id, seq, event_type, from_custodian,
                     to_custodian, occurred_at, geom, temperature_c, condition, notes,
                     prev_hash, hash)
                VALUES (:id, :org, :sample, :seq, :etype, :from_c, :to_c, :occurred_at,
                        {_GEOM_SQL}, :temp, :condition, :notes, :prev_hash, :hash)
                """
            ),
            {
                "id": str(event.id),
                "org": str(event.organization_id),
                "sample": str(event.sample_id),
                "seq": event.seq,
                "etype": event.event_type,
                "from_c": str(event.from_custodian) if event.from_custodian else None,
                "to_c": str(event.to_custodian) if event.to_custodian else None,
                "occurred_at": event.occurred_at,
                **_geo_params(event.geo),
                "temp": event.temperature_c,
                "condition": event.condition,
                "notes": event.notes,
                "prev_hash": event.prev_hash,
                "hash": event.hash,
            },
        )

    async def custody_chain(self, sample_id: UUID) -> list[CustodyEvent]:
        res = await self.session.execute(
            text(
                f"SELECT {_CUSTODY_COLS} FROM custody_events "
                "WHERE sample_id = :s ORDER BY seq"
            ),
            {"s": str(sample_id)},
        )
        return [_custody_from_row(dict(r)) for r in res.mappings().all()]
