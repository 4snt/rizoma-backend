"""Endpoints de laudos — /api/v2/reports e /api/v2/projects/{id}/reports."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.modules.reports import service
from app.modules.reports.schemas import (
    ReportCreate,
    ReportListItem,
    ReportOut,
    VerifyOut,
)
from app.shared.context import Ctx, get_ctx

router = APIRouter(prefix="/api/v2", tags=["reports"])


@router.post(
    "/projects/{project_id}/reports",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_report(project_id: UUID, body: ReportCreate, ctx: Ctx = Depends(get_ctx)):
    return await service.create_report(ctx, project_id, body)


@router.get("/projects/{project_id}/reports", response_model=list[ReportListItem])
async def list_reports(project_id: UUID, ctx: Ctx = Depends(get_ctx)):
    return await service.list_reports(ctx, project_id)


@router.post("/reports/{report_id}/sign", response_model=ReportOut)
async def sign_report(report_id: UUID, request: Request, ctx: Ctx = Depends(get_ctx)):
    return await service.sign_report(ctx, report_id, str(request.base_url))


# PÚBLICO: sem Depends(get_ctx), de propósito. É o destino do QR Code impresso —
# quem escaneia não tem token e não é membro de organização nenhuma. A resposta
# expõe só o necessário para provar autenticidade.
@router.get("/reports/{report_id}/verify", response_model=VerifyOut)
async def verify_report(report_id: UUID, hash: str | None = Query(default=None)):
    return await service.verify_report(report_id, hash)


@router.get("/reports/{report_id}", response_model=ReportOut)
async def get_report(report_id: UUID, ctx: Ctx = Depends(get_ctx)):
    return await service.get_report(ctx, report_id)
