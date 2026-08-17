"""Regras de domínio dos resultados de laboratório.

Camada de aplicação: orquestra repository + entidade (`domain/entities.py`).
O banco já recusa UPDATE/DELETE em `result_versions` (trigger append-only) e
já tem CHECKs para justificativa-na-correção e segregação de funções; este
módulo antecipa essas violações no domínio para devolver um erro HTTP com
significado, em vez de deixar vazar um 500 do Postgres.
"""
from uuid import UUID

from fastapi import HTTPException, status

from app.modules.laboratory.domain.entities import ResultVersion
from app.modules.laboratory.domain.exceptions import (
    InvalidResultError,
    SegregationOfDutiesViolation,
)
from app.modules.laboratory.repository import PgLabResultRepository
from app.shared.context import Ctx
from app.shared.ids import new_id


async def create_result(ctx: Ctx, sample_id: UUID, data) -> dict:
    ctx.require("result:write")
    repo = PgLabResultRepository(ctx.session)

    if not await repo.sample_exists(sample_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Amostra não encontrada.")

    result_id = new_id()
    try:
        first_version = ResultVersion.first(
            id=new_id(),
            organization_id=ctx.org_id,
            result_id=result_id,
            value_numeric=data.value_numeric,
            value_text=data.value_text,
            unit=data.unit,
            lod=data.lod,
            loq=data.loq,
            uncertainty=data.uncertainty,
            created_by=ctx.user_id,
        )
    except InvalidResultError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    await repo.create_header(
        id=result_id,
        organization_id=ctx.org_id,
        sample_id=sample_id,
        analyte=data.analyte,
        method=data.method,
    )
    await repo.append_version(first_version)
    return await get_result(ctx, result_id, permission="result:write")


async def get_result(ctx: Ctx, result_id: UUID, permission: str = "result:read") -> dict:
    ctx.require(permission)
    repo = PgLabResultRepository(ctx.session)
    lab_result = await repo.get(result_id)
    if lab_result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resultado não encontrado.")
    return lab_result.to_dict()


async def list_results(ctx: Ctx, sample_id: UUID) -> list[dict]:
    """Cada resultado vem com a versão corrente E o histórico completo.

    O histórico não é um extra: sem ele, uma correção é indistinguível de uma
    mentira.
    """
    ctx.require("result:read")
    repo = PgLabResultRepository(ctx.session)
    ids = await repo.list_ids_by_sample(sample_id)
    return [await get_result(ctx, result_id) for result_id in ids]


async def list_all_results(
    ctx: Ctx, project_id: UUID | None, sample_id: UUID | None
) -> list[dict]:
    """Resultados da organização inteira, só a versão CORRENTE (o histórico
    completo continua exclusivo de `get_result`/`list_results` na amostra).
    `project_id`/`sample_id` são filtro opcional — projeto e amostra viram
    agregador, não pré-requisito de rota (ver `lims.list_all_samples`)."""
    ctx.require("result:read")
    repo = PgLabResultRepository(ctx.session)
    rows = await repo.list_all(project_id, sample_id)

    results = []
    for row in rows:
        version = ResultVersion(
            id=row["version_id"],
            organization_id=row["version_organization_id"],
            result_id=row["id"],
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
            created_at=row["version_created_at"],
        )
        results.append(
            {
                "id": row["id"],
                "sample_id": row["sample_id"],
                "sample_code": row["sample_code"],
                "project_id": row["project_id"],
                "project_code": row["project_code"],
                "analyte": row["analyte"],
                "method": row["method"],
                "created_at": row["created_at"],
                "current": version.to_dict(),
            }
        )
    return results


async def correct_result(ctx: Ctx, result_id: UUID, data) -> dict:
    """Versão N+1 apontando para a N. A N continua lá."""
    ctx.require("result:write")
    repo = PgLabResultRepository(ctx.session)

    header = await repo.get_header(result_id)
    if header is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resultado não encontrado.")

    prev = await repo.latest_version(result_id)
    if prev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resultado sem versões.")

    try:
        new_version = prev.corrected(
            id=new_id(),
            value_numeric=data.value_numeric,
            value_text=data.value_text,
            unit=data.unit,
            lod=data.lod,
            loq=data.loq,
            uncertainty=data.uncertainty,
            change_reason=data.change_reason,
            created_by=ctx.user_id,
        )
    except InvalidResultError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    await repo.append_version(new_version)
    return await get_result(ctx, result_id, permission="result:write")


async def review_result(ctx: Ctx, result_id: UUID, data) -> dict:
    """Aprova (ou retrata) criando a versão N+1.

    Segregação de funções: quem PRODUZIU o resultado não pode aprová-lo.
    Validado aqui para dar 403 com explicação; o CHECK `chk_segregation` no
    banco é a rede de segurança embaixo.
    """
    ctx.require("result:review")
    repo = PgLabResultRepository(ctx.session)

    header = await repo.get_header(result_id)
    if header is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resultado não encontrado.")

    prev = await repo.latest_version(result_id)
    if prev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resultado sem versões.")

    try:
        prev.assert_can_be_reviewed_by(ctx.user_id)
    except SegregationOfDutiesViolation as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))

    reason = data.note or (
        "Aprovação técnica." if data.status == "approved" else "Resultado retratado."
    )
    new_version = prev.reviewed(
        id=new_id(), reviewer_id=ctx.user_id, new_status=data.status, reason=reason
    )
    await repo.append_version(new_version)
    return await get_result(ctx, result_id, permission="result:review")
