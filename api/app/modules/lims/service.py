"""Regras de negócio do LIMS.

SQL textual (`sqlalchemy.text`) de propósito: o projeto não usa modelos ORM, e a
RLS depende do GUC amarrado por `get_ctx` — a sessão já chega isolada por
organização, então nenhum `WHERE organization_id = ...` extra é necessário para
o isolamento (ele é redundante e está ali só como segunda camada em alguns
pontos).
"""
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.modules.lims import custody
from app.modules.lims.schemas import (
    CustomerCreate,
    ProjectCreate,
    SampleCreate,
    SampleTransition,
)
from app.shared.context import Ctx
from app.shared.ids import new_id

# Colunas de amostra + lat/lon extraídos do geography. `geom` nunca sai cru: o
# cliente quer números, não WKB.
_SAMPLE_COLS = """
    id, organization_id, project_id, code, matrix, treatment_group, replicate,
    status, collected_by, occurred_at, recorded_at, notes, created_at,
    ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon
"""

_CUSTODY_COLS = """
    id, organization_id, sample_id, seq, event_type, from_custodian, to_custodian,
    occurred_at, recorded_at, temperature_c, condition, notes, prev_hash, hash
"""


def _row(result) -> dict[str, Any] | None:
    r = result.mappings().first()
    return dict(r) if r is not None else None


def _rows(result) -> list[dict[str, Any]]:
    return [dict(r) for r in result.mappings().all()]


def _geom_sql() -> str:
    """Fragmento que vira NULL quando lat/lon não vêm.

    O CAST explícito não é decoração: dentro de um CASE, o asyncpg não consegue
    inferir o tipo do parâmetro e estoura AmbiguousParameterError.
    """
    return (
        "CASE WHEN CAST(:lat AS double precision) IS NULL "
        "  OR CAST(:lon AS double precision) IS NULL THEN NULL "
        "ELSE ST_SetSRID(ST_MakePoint("
        "  CAST(:lon AS double precision), CAST(:lat AS double precision)), 4326)::geography END"
    )


# ── Clientes ────────────────────────────────────────────────────────────
async def create_customer(ctx: Ctx, data: CustomerCreate) -> dict[str, Any]:
    try:
        res = await ctx.session.execute(
            text(
                """
                INSERT INTO customers
                    (id, organization_id, name, document, contact_email,
                     contact_phone, notes, created_by)
                VALUES (:id, :org, :name, :document, :email, :phone, :notes, :user)
                RETURNING *
                """
            ),
            {
                "id": str(new_id()),
                "org": str(ctx.org_id),
                "name": data.name,
                "document": data.document,
                "email": data.contact_email,
                "phone": data.contact_phone,
                "notes": data.notes,
                "user": str(ctx.user_id),
            },
        )
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Já existe um cliente chamado '{data.name}' nesta organização.",
        )
    return _row(res)


async def list_customers(ctx: Ctx) -> list[dict[str, Any]]:
    res = await ctx.session.execute(text("SELECT * FROM customers ORDER BY created_at"))
    return _rows(res)


async def get_customer(ctx: Ctx, customer_id: UUID) -> dict[str, Any]:
    res = await ctx.session.execute(
        text("SELECT * FROM customers WHERE id = :id"), {"id": str(customer_id)}
    )
    row = _row(res)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente não encontrado.")
    return row


# ── Projetos ────────────────────────────────────────────────────────────
async def create_project(ctx: Ctx, data: ProjectCreate) -> dict[str, Any]:
    if data.customer_id is not None:
        await get_customer(ctx, data.customer_id)  # 404 se for de outra org (RLS)
    try:
        res = await ctx.session.execute(
            text(
                """
                INSERT INTO projects
                    (id, organization_id, customer_id, code, name, description,
                     marker_type, dada2_params, created_by)
                VALUES (:id, :org, :customer, :code, :name, :description,
                        :marker, CAST(:dada2 AS jsonb), :user)
                RETURNING *
                """
            ),
            {
                "id": str(new_id()),
                "org": str(ctx.org_id),
                "customer": str(data.customer_id) if data.customer_id else None,
                "code": data.code,
                "name": data.name,
                "description": data.description,
                "marker": data.marker_type,
                "dada2": json.dumps(data.dada2_params),
                "user": str(ctx.user_id),
            },
        )
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Já existe um projeto com o código '{data.code}' nesta organização.",
        )
    return _row(res)


async def list_projects(ctx: Ctx) -> list[dict[str, Any]]:
    res = await ctx.session.execute(text("SELECT * FROM projects ORDER BY created_at"))
    return _rows(res)


async def get_project(ctx: Ctx, project_id: UUID) -> dict[str, Any]:
    res = await ctx.session.execute(
        text("SELECT * FROM projects WHERE id = :id"), {"id": str(project_id)}
    )
    row = _row(res)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projeto não encontrado.")
    return row


async def update_project_status(ctx: Ctx, project_id: UUID, new_status: str) -> dict[str, Any]:
    await get_project(ctx, project_id)
    res = await ctx.session.execute(
        text("UPDATE projects SET status = :s WHERE id = :id RETURNING *"),
        {"s": new_status, "id": str(project_id)},
    )
    return _row(res)


# ── Amostras ────────────────────────────────────────────────────────────
async def create_sample(ctx: Ctx, project_id: UUID, data: SampleCreate) -> dict[str, Any]:
    await get_project(ctx, project_id)  # 404 se o projeto for de outra org

    # O tablet gera o UUIDv7 offline; se não veio, o servidor gera.
    sample_id = data.id or new_id()
    try:
        res = await ctx.session.execute(
            text(
                f"""
                INSERT INTO samples
                    (id, organization_id, project_id, code, matrix, treatment_group,
                     replicate, status, geom, collected_by, occurred_at, notes)
                VALUES (:id, :org, :project, :code, :matrix, :group, :replicate,
                        :status, {_geom_sql()}, :user, :occurred_at, :notes)
                RETURNING {_SAMPLE_COLS}
                """
            ),
            {
                "id": str(sample_id),
                "org": str(ctx.org_id),
                "project": str(project_id),
                "code": data.code,
                "matrix": data.matrix,
                "group": data.treatment_group,
                "replicate": data.replicate,
                "status": data.status,
                "lat": data.lat,
                "lon": data.lon,
                "user": str(ctx.user_id),
                "occurred_at": data.occurred_at,
                "notes": data.notes,
            },
        )
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Já existe uma amostra com o código '{data.code}' neste projeto.",
        )
    return _row(res)


async def list_samples(ctx: Ctx, project_id: UUID) -> list[dict[str, Any]]:
    await get_project(ctx, project_id)
    res = await ctx.session.execute(
        text(f"SELECT {_SAMPLE_COLS} FROM samples WHERE project_id = :p ORDER BY code"),
        {"p": str(project_id)},
    )
    return _rows(res)


async def get_sample(ctx: Ctx, sample_id: UUID) -> dict[str, Any]:
    res = await ctx.session.execute(
        text(f"SELECT {_SAMPLE_COLS} FROM samples WHERE id = :id"),
        {"id": str(sample_id)},
    )
    row = _row(res)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Amostra não encontrada.")
    return row


# ── Custódia ────────────────────────────────────────────────────────────
async def transition_sample(
    ctx: Ctx, sample_id: UUID, data: SampleTransition
) -> dict[str, Any]:
    """Transiciona a amostra. A transição NÃO é um UPDATE solto — é um EVENTO.

    O `FOR UPDATE` na amostra serializa duas transições concorrentes: sem ele,
    ambas leriam o mesmo `seq` máximo e uma quebraria no UNIQUE (sample_id, seq)
    — ou pior, gravaria uma cadeia com o mesmo prev_hash em dois ramos.
    """
    locked = await ctx.session.execute(
        text("SELECT id, status FROM samples WHERE id = :id FOR UPDATE"),
        {"id": str(sample_id)},
    )
    row = _row(locked)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Amostra não encontrada.")

    current = row["status"]
    target = data.to_status
    try:
        custody.assert_transition(current, target)
    except custody.InvalidTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))

    last = _row(
        await ctx.session.execute(
            text(
                "SELECT seq, hash, to_custodian FROM custody_events "
                "WHERE sample_id = :s ORDER BY seq DESC LIMIT 1"
            ),
            {"s": str(sample_id)},
        )
    )
    seq = (last["seq"] + 1) if last else 1
    prev_hash = last["hash"] if last else None
    # Quem detinha a amostra passa a ser o `from` do próximo elo.
    from_custodian = last["to_custodian"] if last else None
    to_custodian = data.to_custodian or ctx.user_id
    occurred_at = data.occurred_at or datetime.now(timezone.utc)
    event_type = custody.event_type_for(target)

    event_hash = custody.compute_hash(
        prev_hash=prev_hash,
        sample_id=sample_id,
        seq=seq,
        event_type=event_type,
        occurred_at=occurred_at,
        from_custodian=from_custodian,
        to_custodian=to_custodian,
    )

    await ctx.session.execute(
        text(
            f"""
            INSERT INTO custody_events
                (id, organization_id, sample_id, seq, event_type, from_custodian,
                 to_custodian, occurred_at, geom, temperature_c, condition, notes,
                 prev_hash, hash)
            VALUES (:id, :org, :sample, :seq, :etype, :from_c, :to_c, :occurred_at,
                    {_geom_sql()}, :temp, :condition, :notes, :prev_hash, :hash)
            """
        ),
        {
            "id": str(new_id()),
            "org": str(ctx.org_id),
            "sample": str(sample_id),
            "seq": seq,
            "etype": event_type,
            "from_c": str(from_custodian) if from_custodian else None,
            "to_c": str(to_custodian) if to_custodian else None,
            "occurred_at": occurred_at,
            "lat": data.lat,
            "lon": data.lon,
            "temp": data.temperature_c,
            "condition": data.condition,
            "notes": data.notes,
            "prev_hash": prev_hash,
            "hash": event_hash,
        },
    )

    # Mesma transação: ou o evento e o novo estado existem juntos, ou nenhum dos
    # dois. Um estado sem evento correspondente seria um buraco na rastreabilidade.
    updated = await ctx.session.execute(
        text(f"UPDATE samples SET status = :s WHERE id = :id RETURNING {_SAMPLE_COLS}"),
        {"s": target, "id": str(sample_id)},
    )
    return _row(updated)


async def get_custody_chain(ctx: Ctx, sample_id: UUID) -> dict[str, Any]:
    await get_sample(ctx, sample_id)
    events = _rows(
        await ctx.session.execute(
            text(
                f"SELECT {_CUSTODY_COLS} FROM custody_events "
                "WHERE sample_id = :s ORDER BY seq"
            ),
            {"s": str(sample_id)},
        )
    )
    return {
        "sample_id": sample_id,
        "events": events,
        "chain_valid": custody.verify_chain(events),
    }


# ── Idempotência ────────────────────────────────────────────────────────
async def idempotent_replay(
    ctx: Ctx, key: str | None, endpoint: str
) -> tuple[int, Any] | None:
    """Se a chave já foi usada nesta org, devolve (status, body) gravados."""
    if not key:
        return None
    row = _row(
        await ctx.session.execute(
            text(
                "SELECT response_status, response_body FROM idempotency_keys "
                "WHERE key = :k AND organization_id = :o"
            ),
            {"k": key, "o": str(ctx.org_id)},
        )
    )
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
