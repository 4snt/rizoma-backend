"""Persistência do LIMS. Todo `sqlalchemy.text()` do módulo mora aqui — o
`service.py` não fala SQL, só entidades.

Recebe a `AsyncSession` já aberta pelo `Ctx` (não abre conexão própria como o
`get_pool()` do v1): a RLS depende do `SET LOCAL app.organization_id` já
aplicado nessa sessão pelo `shared/context.py`, então o repository herda o
isolamento de graça, sem precisar repetir `WHERE organization_id = ...`.
"""
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.lims.domain.entities import (
    CustodyEvent,
    Project,
    Sample,
    SampleGene,
    SampleTest,
)
from app.modules.lims.domain.exceptions import DuplicateError
from app.modules.lims.domain.value_objects import GeoPoint

_SAMPLE_BIO_COLS = (
    "organism_type, colonia_forma, colonia_elevacao, colonia_margem, "
    "colonia_cor, colonia_textura, colonia_tamanho_mm, colonia_opacidade"
)

_SAMPLE_COLS = f"""
    id, organization_id, project_id, code, matrix, treatment_group, replicate,
    status, collected_by, occurred_at, recorded_at, notes, created_at,
    ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon, {_SAMPLE_BIO_COLS}
"""

_CUSTODY_COLS = """
    id, organization_id, sample_id, seq, event_type, from_custodian, to_custodian,
    occurred_at, recorded_at, temperature_c, condition, notes, prev_hash, hash
"""

_SAMPLE_TEST_COLS = """
    id, organization_id, sample_id, test_name, result, method, tested_at,
    notes, created_by, created_at, updated_at
"""

_SAMPLE_GENE_COLS = """
    id, organization_id, sample_id, gene, purpose, result, ncbi_accession,
    method, tested_at, notes, created_by, created_at, updated_at
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
        status=row["status"],
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
        organism_type=row.get("organism_type"),
        colonia_forma=row.get("colonia_forma"),
        colonia_elevacao=row.get("colonia_elevacao"),
        colonia_margem=row.get("colonia_margem"),
        colonia_cor=row.get("colonia_cor"),
        colonia_textura=row.get("colonia_textura"),
        colonia_tamanho_mm=(
            float(row["colonia_tamanho_mm"]) if row.get("colonia_tamanho_mm") is not None else None
        ),
        colonia_opacidade=row.get("colonia_opacidade"),
    )


def _sample_test_from_row(row: dict[str, Any]) -> SampleTest:
    return SampleTest(
        id=row["id"],
        organization_id=row["organization_id"],
        sample_id=row["sample_id"],
        test_name=row["test_name"],
        result=row["result"],
        method=row["method"],
        tested_at=row["tested_at"],
        notes=row["notes"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _sample_gene_from_row(row: dict[str, Any]) -> SampleGene:
    return SampleGene(
        id=row["id"],
        organization_id=row["organization_id"],
        sample_id=row["sample_id"],
        gene=row["gene"],
        purpose=row["purpose"],
        result=row["result"],
        ncbi_accession=row["ncbi_accession"],
        method=row["method"],
        tested_at=row["tested_at"],
        notes=row["notes"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
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
                         created_by)
                    VALUES (:id, :org, :customer, :code, :name, :description, :user)
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
                         replicate, status, geom, collected_by, occurred_at, notes,
                         organism_type, colonia_forma, colonia_elevacao, colonia_margem,
                         colonia_cor, colonia_textura, colonia_tamanho_mm, colonia_opacidade)
                    VALUES (:id, :org, :project, :code, :matrix, :group, :replicate,
                            :status, {_GEOM_SQL}, :user, :occurred_at, :notes,
                            :organism_type, :colonia_forma, :colonia_elevacao, :colonia_margem,
                            :colonia_cor, :colonia_textura, :colonia_tamanho_mm, :colonia_opacidade)
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
                    "organism_type": sample.organism_type,
                    "colonia_forma": sample.colonia_forma,
                    "colonia_elevacao": sample.colonia_elevacao,
                    "colonia_margem": sample.colonia_margem,
                    "colonia_cor": sample.colonia_cor,
                    "colonia_textura": sample.colonia_textura,
                    "colonia_tamanho_mm": sample.colonia_tamanho_mm,
                    "colonia_opacidade": sample.colonia_opacidade,
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

    async def list_all(self, project_id: UUID | None) -> list[dict[str, Any]]:
        """Amostras de toda a organização, projeto opcional só como filtro.

        Projeto deixa de ser pré-requisito pra listar — é agregador, não
        dono. Uma query só (join com `projects` pro código/nome exibido);
        RLS já isola por organização, então não precisa repetir
        `organization_id` aqui — e não é N+1 por projeto no frontend.
        """
        res = await self.session.execute(
            text(
                """
                SELECT
                    s.id, s.organization_id, s.project_id, s.code, s.matrix,
                    s.treatment_group, s.replicate, s.status, s.collected_by,
                    s.occurred_at, s.recorded_at, s.notes, s.created_at,
                    ST_Y(s.geom::geometry) AS lat, ST_X(s.geom::geometry) AS lon,
                    s.organism_type, s.colonia_forma, s.colonia_elevacao, s.colonia_margem,
                    s.colonia_cor, s.colonia_textura, s.colonia_tamanho_mm, s.colonia_opacidade,
                    p.code AS project_code, p.name AS project_name
                FROM samples s
                JOIN projects p ON p.id = s.project_id
                WHERE (CAST(:project_id AS uuid) IS NULL OR s.project_id = :project_id)
                ORDER BY s.created_at DESC
                """
            ),
            {"project_id": str(project_id) if project_id else None},
        )
        return [dict(r) for r in res.mappings().all()]

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

    async def update_morphology(self, sample_id: UUID, fields: dict[str, Any]) -> Sample | None:
        """UPDATE parcial dos campos biológicos — só grava o que veio em
        `fields` (chaves de `SampleMorphologyUpdate` com valor setado)."""
        if not fields:
            return await self.get(sample_id)
        assignments = ", ".join(f"{col} = :{col}" for col in fields)
        res = await self.session.execute(
            text(f"UPDATE samples SET {assignments} WHERE id = :id RETURNING {_SAMPLE_COLS}"),
            {**fields, "id": str(sample_id)},
        )
        row = res.mappings().first()
        return _sample_from_row(dict(row)) if row is not None else None

    async def create_test(self, test: SampleTest) -> SampleTest:
        res = await self.session.execute(
            text(
                f"""
                INSERT INTO sample_tests
                    (id, organization_id, sample_id, test_name, result, method,
                     tested_at, notes, created_by)
                VALUES (:id, :org, :sample, :test_name, :result, :method,
                        :tested_at, :notes, :user)
                RETURNING {_SAMPLE_TEST_COLS}
                """
            ),
            {
                "id": str(test.id),
                "org": str(test.organization_id),
                "sample": str(test.sample_id),
                "test_name": test.test_name,
                "result": test.result,
                "method": test.method,
                "tested_at": test.tested_at,
                "notes": test.notes,
                "user": str(test.created_by) if test.created_by else None,
            },
        )
        return _sample_test_from_row(dict(res.mappings().first()))

    async def list_tests(self, sample_id: UUID) -> list[SampleTest]:
        res = await self.session.execute(
            text(
                f"SELECT {_SAMPLE_TEST_COLS} FROM sample_tests "
                "WHERE sample_id = :s ORDER BY created_at"
            ),
            {"s": str(sample_id)},
        )
        return [_sample_test_from_row(dict(r)) for r in res.mappings().all()]

    async def create_gene(self, gene: SampleGene) -> SampleGene:
        res = await self.session.execute(
            text(
                f"""
                INSERT INTO sample_genes
                    (id, organization_id, sample_id, gene, purpose, result,
                     ncbi_accession, method, tested_at, notes, created_by)
                VALUES (:id, :org, :sample, :gene, :purpose, :result,
                        :ncbi_accession, :method, :tested_at, :notes, :user)
                RETURNING {_SAMPLE_GENE_COLS}
                """
            ),
            {
                "id": str(gene.id),
                "org": str(gene.organization_id),
                "sample": str(gene.sample_id),
                "gene": gene.gene,
                "purpose": gene.purpose,
                "result": gene.result,
                "ncbi_accession": gene.ncbi_accession,
                "method": gene.method,
                "tested_at": gene.tested_at,
                "notes": gene.notes,
                "user": str(gene.created_by) if gene.created_by else None,
            },
        )
        return _sample_gene_from_row(dict(res.mappings().first()))

    async def list_genes(self, sample_id: UUID) -> list[SampleGene]:
        res = await self.session.execute(
            text(
                f"SELECT {_SAMPLE_GENE_COLS} FROM sample_genes "
                "WHERE sample_id = :s ORDER BY created_at"
            ),
            {"s": str(sample_id)},
        )
        return [_sample_gene_from_row(dict(r)) for r in res.mappings().all()]

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
