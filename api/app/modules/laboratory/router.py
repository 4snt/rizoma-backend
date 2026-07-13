"""Endpoints de laboratório — /api/v2/lab."""
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.modules.laboratory import service
from app.modules.laboratory.schemas import (
    ResultCorrect,
    ResultCreate,
    ResultOut,
    ResultReview,
)
from app.shared.context import Ctx, get_ctx

router = APIRouter(prefix="/api/v2/lab", tags=["laboratory"])


@router.post(
    "/samples/{sample_id}/results",
    response_model=ResultOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_result(sample_id: UUID, body: ResultCreate, ctx: Ctx = Depends(get_ctx)):
    return await service.create_result(ctx, sample_id, body)


@router.get("/samples/{sample_id}/results", response_model=list[ResultOut])
async def list_results(sample_id: UUID, ctx: Ctx = Depends(get_ctx)):
    return await service.list_results(ctx, sample_id)


@router.get("/results/{result_id}", response_model=ResultOut)
async def get_result(result_id: UUID, ctx: Ctx = Depends(get_ctx)):
    return await service.get_result(ctx, result_id)


@router.post("/results/{result_id}/correct", response_model=ResultOut)
async def correct_result(result_id: UUID, body: ResultCorrect, ctx: Ctx = Depends(get_ctx)):
    return await service.correct_result(ctx, result_id, body)


@router.post("/results/{result_id}/review", response_model=ResultOut)
async def review_result(result_id: UUID, body: ResultReview, ctx: Ctx = Depends(get_ctx)):
    return await service.review_result(ctx, result_id, body)
