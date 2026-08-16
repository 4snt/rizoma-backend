"""Rotas de interoperabilidade. Montadas pelo main.py em /api/v2/interop
(tcc-rizoma#10)."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import PlainTextResponse

from app.modules.interop import service
from app.modules.interop.schemas import (
    SampleImportResult,
    WebhookSubscriptionCreate,
    WebhookSubscriptionCreated,
    WebhookSubscriptionOut,
)
from app.shared.context import Ctx, get_ctx

router = APIRouter(tags=["interop"])

CtxDep = Annotated[Ctx, Depends(get_ctx)]


# ── Webhooks ─────────────────────────────────────────────────────────────
@router.post(
    "/webhooks", response_model=WebhookSubscriptionCreated, status_code=status.HTTP_201_CREATED
)
async def create_webhook(data: WebhookSubscriptionCreate, ctx: CtxDep) -> WebhookSubscriptionCreated:
    return WebhookSubscriptionCreated(**await service.create_webhook(ctx, data))


@router.get("/webhooks", response_model=list[WebhookSubscriptionOut])
async def list_webhooks(ctx: CtxDep) -> list[WebhookSubscriptionOut]:
    return [WebhookSubscriptionOut(**w) for w in await service.list_webhooks(ctx)]


@router.delete("/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(webhook_id: UUID, ctx: CtxDep) -> None:
    await service.delete_webhook(ctx, webhook_id)


# ── Import/export de amostras ─────────────────────────────────────────────
@router.get("/projects/{project_id}/samples/export")
async def export_samples(project_id: UUID, ctx: CtxDep) -> PlainTextResponse:
    csv_text = await service.export_samples_csv(ctx, project_id)
    return PlainTextResponse(
        csv_text, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="samples-{project_id}.csv"'},
    )


@router.post("/projects/{project_id}/samples/import", response_model=SampleImportResult)
async def import_samples(
    project_id: UUID, ctx: CtxDep, file: UploadFile = File(...)
) -> SampleImportResult:
    csv_text = (await file.read()).decode("utf-8-sig")  # -sig: aceita CSV exportado do Excel com BOM
    result = await service.import_samples_csv(ctx, project_id, csv_text)
    return SampleImportResult(**result)
