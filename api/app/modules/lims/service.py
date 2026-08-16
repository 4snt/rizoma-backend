"""Regras de negócio do LIMS.

Camada de aplicação: orquestra repository (persistência) e entidade/domínio
(`custody.py`, `domain/entities.py`), e traduz exceções de domínio para HTTP.
Não fala SQL — isso é `repository.py`.
"""
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text

from app.modules.lims import custody
from app.modules.lims.domain.entities import CustodyEvent, Customer, Project, Sample
from app.modules.lims.domain.exceptions import DuplicateError
from app.modules.lims.domain.value_objects import GeoPoint
from app.modules.lims.repository import (
    PgCustomerRepository,
    PgProjectRepository,
    PgSampleRepository,
)
from app.modules.lims.schemas import (
    CustomerCreate,
    ProjectCreate,
    SampleCreate,
    SampleTransition,
)
from app.shared.context import Ctx
from app.shared.ids import new_id


# ── Clientes ────────────────────────────────────────────────────────────
async def create_customer(ctx: Ctx, data: CustomerCreate) -> dict[str, Any]:
    repo = PgCustomerRepository(ctx.session)
    customer = Customer(
        id=new_id(),
        organization_id=ctx.org_id,
        name=data.name,
        document=data.document,
        contact_email=data.contact_email,
        contact_phone=data.contact_phone,
        notes=data.notes,
        created_by=ctx.user_id,
    )
    try:
        saved = await repo.create(customer)
    except DuplicateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return saved.to_dict()


async def list_customers(ctx: Ctx) -> list[dict[str, Any]]:
    repo = PgCustomerRepository(ctx.session)
    return [c.to_dict() for c in await repo.list_all()]


async def get_customer(ctx: Ctx, customer_id: UUID) -> dict[str, Any]:
    repo = PgCustomerRepository(ctx.session)
    customer = await repo.get(customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente não encontrado.")
    return customer.to_dict()


# ── Projetos ────────────────────────────────────────────────────────────
async def create_project(ctx: Ctx, data: ProjectCreate) -> dict[str, Any]:
    if data.customer_id is not None:
        await get_customer(ctx, data.customer_id)  # 404 se for de outra org (RLS)

    repo = PgProjectRepository(ctx.session)
    project = Project(
        id=new_id(),
        organization_id=ctx.org_id,
        customer_id=data.customer_id,
        code=data.code,
        name=data.name,
        description=data.description,
        marker_type=data.marker_type,
        dada2_params=data.dada2_params,
        analyses=data.analyses,
        created_by=ctx.user_id,
    )
    try:
        saved = await repo.create(project)
    except DuplicateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return saved.to_dict()


async def list_projects(ctx: Ctx) -> list[dict[str, Any]]:
    repo = PgProjectRepository(ctx.session)
    return [p.to_dict() for p in await repo.list_all()]


async def get_project(ctx: Ctx, project_id: UUID) -> dict[str, Any]:
    repo = PgProjectRepository(ctx.session)
    project = await repo.get(project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projeto não encontrado.")
    return project.to_dict()


async def update_project_status(ctx: Ctx, project_id: UUID, new_status: str) -> dict[str, Any]:
    await get_project(ctx, project_id)
    repo = PgProjectRepository(ctx.session)
    updated = await repo.update_status(project_id, new_status)
    return updated.to_dict()


# ── Amostras ────────────────────────────────────────────────────────────
async def create_sample(ctx: Ctx, project_id: UUID, data: SampleCreate) -> dict[str, Any]:
    await get_project(ctx, project_id)  # 404 se o projeto for de outra org

    repo = PgSampleRepository(ctx.session)
    # O tablet gera o UUIDv7 offline; se não veio, o servidor gera.
    sample = Sample(
        id=data.id or new_id(),
        organization_id=ctx.org_id,
        project_id=project_id,
        code=data.code,
        matrix=data.matrix,
        status=data.status,
        treatment_group=data.treatment_group,
        replicate=data.replicate,
        geo=GeoPoint.from_optional(data.lat, data.lon),
        collected_by=ctx.user_id,
        occurred_at=data.occurred_at,
        notes=data.notes,
    )
    try:
        saved = await repo.create(sample)
    except DuplicateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return saved.to_dict()


async def list_samples(ctx: Ctx, project_id: UUID) -> list[dict[str, Any]]:
    await get_project(ctx, project_id)
    repo = PgSampleRepository(ctx.session)
    return [s.to_dict() for s in await repo.list_by_project(project_id)]


async def get_sample(ctx: Ctx, sample_id: UUID) -> dict[str, Any]:
    repo = PgSampleRepository(ctx.session)
    sample = await repo.get(sample_id)
    if sample is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Amostra não encontrada.")
    return sample.to_dict()


# ── Custódia ────────────────────────────────────────────────────────────
async def transition_sample(
    ctx: Ctx, sample_id: UUID, data: SampleTransition
) -> dict[str, Any]:
    """Transiciona a amostra. A transição NÃO é um UPDATE solto — é um EVENTO.

    O lock de `get_for_update` serializa duas transições concorrentes da mesma
    amostra (ver docstring do repository); a validação da transição e o
    cálculo do hash encadeado são regra de domínio (`Sample`/`CustodyEvent`),
    não SQL.
    """
    repo = PgSampleRepository(ctx.session)

    sample = await repo.get_for_update(sample_id)
    if sample is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Amostra não encontrada.")

    target = data.to_status
    try:
        sample.assert_can_transition_to(target)
    except custody.InvalidTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))

    last_event = await repo.last_custody_event(sample_id)
    occurred_at = data.occurred_at or datetime.now(timezone.utc)

    event = CustodyEvent.next_in_chain(
        id=new_id(),
        organization_id=ctx.org_id,
        sample_id=sample_id,
        last_event=last_event,
        target_status=target,
        to_custodian=data.to_custodian or ctx.user_id,
        occurred_at=occurred_at,
        geo=GeoPoint.from_optional(data.lat, data.lon),
        temperature_c=data.temperature_c,
        condition=data.condition,
        notes=data.notes,
    )

    await repo.append_custody_event(event)

    # Mesma transação: ou o evento e o novo estado existem juntos, ou nenhum
    # dos dois. Um estado sem evento correspondente seria um buraco na
    # rastreabilidade.
    updated = await repo.update_status(sample_id, target)
    return updated.to_dict()


async def get_custody_chain(ctx: Ctx, sample_id: UUID) -> dict[str, Any]:
    await get_sample(ctx, sample_id)
    repo = PgSampleRepository(ctx.session)
    events = await repo.custody_chain(sample_id)
    event_dicts = [e.to_dict() for e in events]
    return {
        "sample_id": sample_id,
        "events": event_dicts,
        "chain_valid": custody.verify_chain(event_dicts),
    }


# ── Idempotência ────────────────────────────────────────────────────────
# Cross-cutting de infraestrutura, não domínio do LIMS — fica de fora do
# repository/entidade de propósito, assim como o dual-engine de `identity`.
async def idempotent_replay(
    ctx: Ctx, key: str | None, endpoint: str
) -> tuple[int, Any] | None:
    """Se a chave já foi usada nesta org, devolve (status, body) gravados."""
    if not key:
        return None
    res = await ctx.session.execute(
        text(
            "SELECT response_status, response_body FROM idempotency_keys "
            "WHERE key = :k AND organization_id = :o"
        ),
        {"k": key, "o": str(ctx.org_id)},
    )
    row = res.mappings().first()
    if row is None:
        return None
    return row["response_status"], row["response_body"]


async def idempotent_store(
    ctx: Ctx, key: str | None, endpoint: str, status_code: int, body: Any
) -> None:
    if not key:
        return
    await ctx.session.execute(
        text(
            """
            INSERT INTO idempotency_keys
                (key, organization_id, user_id, endpoint, response_status, response_body)
            VALUES (:k, :o, :u, :e, :s, CAST(:b AS jsonb))
            ON CONFLICT (key) DO NOTHING
            """
        ),
        {
            "k": key,
            "o": str(ctx.org_id),
            "u": str(ctx.user_id),
            "e": endpoint,
            "s": status_code,
            "b": json.dumps(body, default=str),
        },
    )
