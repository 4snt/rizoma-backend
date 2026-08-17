"""Monta o snapshot de conteúdo de um laudo, lendo projeto/cliente/amostras/
resultados/bioinformática de OUTROS módulos.

Isto não é `repository.py` de propósito: um repository é escopado ao próprio
agregado (Laudo); isto é uma leitura de aplicação que atravessa módulos, o
equivalente a um *read model* de CQRS. Acoplar por import direto aos serviços
de `lims`/`laboratory`/`jobs` criaria dependência circular entre fatias
verticais — daí o SELECT direto, como já era antes desta refatoração.
"""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text

from app.modules.reports.domain.entities import jsonable
from app.shared.context import Ctx


def _summarize(data: Any) -> str:
    if not isinstance(data, dict) or not data:
        return "Sem resumo estruturado."
    parts = []
    for k, v in list(data.items())[:6]:
        if isinstance(v, (list, tuple)):
            parts.append(f"{k}: {len(v)} registro(s)")
        elif isinstance(v, dict):
            parts.append(f"{k}: {len(v)} campo(s)")
        else:
            parts.append(f"{k}: {v}")
    return "; ".join(parts)


async def build_snapshot(ctx: Ctx, project_id: UUID, title: str) -> dict[str, Any]:
    s = ctx.session

    project = (
        await s.execute(
            text(
                "SELECT p.id, p.code, p.name, p.description, p.marker_type, p.status, "
                "       p.customer_user_id, o.name AS org_name, o.cnpj AS org_cnpj "
                "FROM projects p JOIN organizations o ON o.id = p.organization_id "
                "WHERE p.id = :p"
            ),
            {"p": str(project_id)},
        )
    ).first()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projeto não encontrado.")

    # "Pesquisador"/"cliente" agora é sempre um organization_member (conta
    # Google) — o laudo cita nome e e-mail do usuário, não mais um contato
    # solto de tabela própria.
    customer = None
    if project.customer_user_id:
        customer = (
            await s.execute(
                text("SELECT name, email FROM users WHERE id = :u"),
                {"u": str(project.customer_user_id)},
            )
        ).first()

    samples = (
        await s.execute(
            text(
                "SELECT id, code, matrix, treatment_group, replicate, status, occurred_at "
                "FROM samples WHERE project_id = :p ORDER BY code"
            ),
            {"p": str(project_id)},
        )
    ).fetchall()

    # Só resultados cuja versão CORRENTE está aprovada. Um laudo não carrega
    # rascunho nem resultado retratado.
    results = (
        await s.execute(
            text(
                """
                SELECT sm.code AS sample_code, lr.analyte, lr.method,
                       v.value_numeric, v.value_text, v.unit, v.lod, v.loq,
                       v.uncertainty, v.below_lod, v.version, v.created_at
                FROM lab_results lr
                JOIN samples sm ON sm.id = lr.sample_id
                JOIN LATERAL (
                    SELECT * FROM result_versions rv
                    WHERE rv.result_id = lr.id
                    ORDER BY rv.version DESC LIMIT 1
                ) v ON true
                WHERE sm.project_id = :p AND v.status = 'approved'
                ORDER BY sm.code, lr.analyte
                """
            ),
            {"p": str(project_id)},
        )
    ).fetchall()

    # Bioinformática: SELECT direto (o módulo jobs é de outra fatia — acoplar os
    # dois por import criaria dependência circular).
    bio = (
        await s.execute(
            text(
                """
                SELECT ar.analysis_type, ar.result_data, ar.created_at, j.job_type
                FROM analysis_results ar
                JOIN pipeline_jobs j ON j.id = ar.job_id
                WHERE j.project_id = :p AND j.status = 'completed'
                ORDER BY ar.created_at
                """
            ),
            {"p": str(project_id)},
        )
    ).fetchall()

    content = {
        "title": title,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "organization": {"name": project.org_name, "cnpj": project.org_cnpj},
        "project": {
            "code": project.code,
            "name": project.name,
            "description": project.description,
            "marker_type": project.marker_type,
            "status": project.status,
        },
        "customer": (
            {
                "name": customer.name,
                "contact_email": customer.email,
            }
            if customer
            else None
        ),
        "samples": [
            {
                "code": r.code,
                "matrix": r.matrix,
                "treatment_group": r.treatment_group,
                "replicate": r.replicate,
                "status": r.status,
                "occurred_at": r.occurred_at,
            }
            for r in samples
        ],
        "results": [
            {
                "sample_code": r.sample_code,
                "analyte": r.analyte,
                "method": r.method,
                "value_numeric": r.value_numeric,
                "value_text": r.value_text,
                "unit": r.unit,
                "lod": r.lod,
                "loq": r.loq,
                "uncertainty": r.uncertainty,
                "below_lod": r.below_lod,
                "display_value": (
                    f"<{r.lod}"
                    if r.below_lod and r.lod is not None
                    else (str(r.value_numeric) if r.value_numeric is not None else r.value_text)
                ),
                "version": r.version,
            }
            for r in results
        ],
        "bioinformatics": [
            {
                "analysis_type": r.analysis_type,
                "job_type": r.job_type,
                "summary": _summarize(r.result_data),
                "created_at": r.created_at,
            }
            for r in bio
        ],
    }
    return jsonable(content)
