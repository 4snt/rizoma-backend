"""Rotas do LIMS. Montadas pelo main.py em /api/v2/lims."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status  # noqa: F401
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.modules.lims import service
from app.modules.lims.schemas import (
    CustodyChainOut,
    CustomerCreate,
    CustomerOut,
    ProjectCreate,
    ProjectOut,
    ProjectStatusUpdate,
    SampleCreate,
    SampleOut,
    SampleTransition,
)
from app.shared.context import Ctx, get_ctx

router = APIRouter(tags=["lims"])

CtxDep = Annotated[Ctx, Depends(get_ctx)]


# ── Clientes ────────────────────────────────────────────────────────────
@router.post("/customers", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
async def create_customer(data: CustomerCreate, ctx: CtxDep) -> CustomerOut:
    ctx.require("customer:write")
    return CustomerOut(**await service.create_customer(ctx, data))


@router.get("/customers", response_model=list[CustomerOut])
async def list_customers(ctx: CtxDep) -> list[CustomerOut]:
    ctx.require("customer:read")
    return [CustomerOut(**r) for r in await service.list_customers(ctx)]


@router.get("/customers/{customer_id}", response_model=CustomerOut)
async def get_customer(customer_id: UUID, ctx: CtxDep) -> CustomerOut:
    ctx.require("customer:read")
    return CustomerOut(**await service.get_customer(ctx, customer_id))


# ── Projetos ────────────────────────────────────────────────────────────
@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(data: ProjectCreate, ctx: CtxDep) -> ProjectOut:
    ctx.require("project:write")
    return ProjectOut(**await service.create_project(ctx, data))


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(ctx: CtxDep) -> list[ProjectOut]:
    ctx.require("project:read")
    return [ProjectOut(**r) for r in await service.list_projects(ctx)]


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: UUID, ctx: CtxDep) -> ProjectOut:
    ctx.require("project:read")
    return ProjectOut(**await service.get_project(ctx, project_id))


@router.patch("/projects/{project_id}/status", response_model=ProjectOut)
async def update_project_status(
    project_id: UUID, data: ProjectStatusUpdate, ctx: CtxDep
) -> ProjectOut:
    ctx.require("project:write")
    return ProjectOut(**await service.update_project_status(ctx, project_id, data.status))


# ── Amostras ────────────────────────────────────────────────────────────
@router.post("/projects/{project_id}/samples", status_code=status.HTTP_201_CREATED)
async def create_sample(
    project_id: UUID,
    data: SampleCreate,
    ctx: CtxDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Response:
    """Cria amostra. Idempotente: o tablet em campo reenvia sem medo.

    A rede do campo cai no meio do POST. O tablet não sabe se o servidor gravou,
    então reenvia. Com a mesma Idempotency-Key, a segunda chamada devolve a
    resposta gravada da primeira — sem criar uma amostra fantasma.
    """
    ctx.require("sample:write")
    endpoint = f"POST /projects/{project_id}/samples"

    replay = await service.idempotent_replay(ctx, idempotency_key, endpoint)
    if replay is not None:
        replay_status, replay_body = replay
        return JSONResponse(
            status_code=replay_status or status.HTTP_201_CREATED,
            content=replay_body,
            headers={"Idempotent-Replay": "true"},
        )

    sample = SampleOut(**await service.create_sample(ctx, project_id, data))
    body = jsonable_encoder(sample)
    await service.idempotent_store(
        ctx, idempotency_key, endpoint, status.HTTP_201_CREATED, body
    )
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=body)


@router.get("/projects/{project_id}/samples", response_model=list[SampleOut])
async def list_samples(project_id: UUID, ctx: CtxDep) -> list[SampleOut]:
    ctx.require("sample:read")
    return [SampleOut(**r) for r in await service.list_samples(ctx, project_id)]


@router.get("/samples/{sample_id}", response_model=SampleOut)
async def get_sample(sample_id: UUID, ctx: CtxDep) -> SampleOut:
    ctx.require("sample:read")
    return SampleOut(**await service.get_sample(ctx, sample_id))


@router.post("/samples/{sample_id}/transition", response_model=SampleOut)
async def transition_sample(
    sample_id: UUID, data: SampleTransition, ctx: CtxDep
) -> SampleOut:
    ctx.require("sample:write")
    return SampleOut(**await service.transition_sample(ctx, sample_id, data))


@router.get("/samples/{sample_id}/custody", response_model=CustodyChainOut)
async def get_custody_chain(sample_id: UUID, ctx: CtxDep) -> CustodyChainOut:
    ctx.require("sample:read")
    return CustodyChainOut(**await service.get_custody_chain(ctx, sample_id))
