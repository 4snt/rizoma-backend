"""Rotas do catálogo de arquivos — /api/v2/files."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.shared.context import Ctx, get_ctx

from . import service
from .schemas import ConfirmRequest, DownloadResponse, FileOut, PresignRequest, PresignResponse

router = APIRouter(prefix="/api/v2/files", tags=["files"])


@router.post("/presign", response_model=PresignResponse, status_code=status.HTTP_201_CREATED)
async def presign(req: PresignRequest, ctx: Ctx = Depends(get_ctx)) -> PresignResponse:
    return await service.presign(ctx, req)


@router.post("/{file_id}/confirm", response_model=FileOut)
async def confirm(
    file_id: UUID, req: ConfirmRequest, ctx: Ctx = Depends(get_ctx)
) -> FileOut:
    return await service.confirm(ctx, file_id, req.sha256)


@router.get("/{file_id}/download", response_model=DownloadResponse)
async def download(file_id: UUID, ctx: Ctx = Depends(get_ctx)) -> DownloadResponse:
    return DownloadResponse(url=await service.download_url(ctx, file_id))


@router.get("/", response_model=list[FileOut])
async def list_files(
    project_id: UUID | None = Query(default=None),
    sample_id: UUID | None = Query(default=None),
    ctx: Ctx = Depends(get_ctx),
) -> list[FileOut]:
    return await service.list_files(ctx, project_id, sample_id)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(file_id: UUID, ctx: Ctx = Depends(get_ctx)) -> None:
    await service.delete_file(ctx, file_id)
