"""Regras de interoperabilidade (tcc-rizoma#10): webhooks + import/export CSV
de amostras.

Import/export reaproveita `lims_service.create_sample`/`list_samples` — é
composição de casos de uso já existentes, com validação (matrix, status,
duplicidade de código) já garantida por aquele módulo. Não reimplementa nada.
"""
import csv
import hashlib
import hmac
import io
import json
import logging
import secrets
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.interop.repository import PgWebhookRepository
from app.modules.interop.schemas import (
    WEBHOOK_EVENT_TYPES,
    SampleImportRowError,
    WebhookSubscriptionCreate,
)
from app.modules.lims import service as lims_service
from app.modules.lims.schemas import SampleCreate
from app.shared.context import Ctx
from app.shared.ids import new_id

logger = logging.getLogger(__name__)

_WEBHOOK_TIMEOUT_SECONDS = 5.0
_SAMPLE_CSV_HEADER = ("code", "matrix", "treatment_group", "replicate", "lat", "lon", "notes")


# ── Webhooks (CRUD do usuário, sessão com tenant) ────────────────────────
async def create_webhook(ctx: Ctx, data: WebhookSubscriptionCreate) -> dict[str, Any]:
    ctx.require("member:write")  # mesma trilha de permissão de config de organização
    unknown = set(data.event_types) - set(WEBHOOK_EVENT_TYPES)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"event_types desconhecido: {sorted(unknown)}. Válidos: {list(WEBHOOK_EVENT_TYPES)}.",
        )
    secret = secrets.token_urlsafe(32)
    row = await PgWebhookRepository(ctx.session).create(
        id_=new_id(), organization_id=ctx.org_id, url=str(data.url),
        event_types=data.event_types, secret=secret, created_by=ctx.user_id,
    )
    return row


async def list_webhooks(ctx: Ctx) -> list[dict[str, Any]]:
    ctx.require("member:read")
    return await PgWebhookRepository(ctx.session).list_for_org(ctx.org_id)


async def delete_webhook(ctx: Ctx, webhook_id: UUID) -> None:
    ctx.require("member:write")
    found = await PgWebhookRepository(ctx.session).delete(webhook_id, ctx.org_id)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assinatura de webhook não encontrada.")


# ── Dispatch (chamado de dentro de outros módulos, sessão system) ───────
async def dispatch_event(
    session: AsyncSession, organization_id: UUID, event_type: str, payload: dict[str, Any]
) -> None:
    """Best-effort: nunca deixa uma falha de webhook derrubar o fluxo que
    disparou o evento (ex: worker completando um job). Assinatura HMAC-SHA256
    do corpo em `X-Rizoma-Signature`, pro assinante verificar autenticidade.
    """
    subs = await PgWebhookRepository(session).active_for_event(organization_id, event_type)
    if not subs:
        return

    body = {"event": event_type, "organization_id": str(organization_id), "data": payload}
    raw = json.dumps(body).encode()
    async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT_SECONDS) as client:
        for sub in subs:
            signature = hmac.new(sub["secret"].encode(), raw, hashlib.sha256).hexdigest()
            try:
                await client.post(
                    sub["url"], content=raw,
                    headers={"Content-Type": "application/json", "X-Rizoma-Signature": signature},
                )
            except httpx.HTTPError:
                logger.warning("webhook %s falhou pra %s (evento %s)", sub["id"], sub["url"], event_type)


# ── Import/export de amostras (CSV) ──────────────────────────────────────
async def export_samples_csv(ctx: Ctx, project_id: UUID) -> str:
    # `lims_service.list_samples` não checa papel (a checagem normal mora no
    # router de lims, não no service) — como aqui a gente chama o service
    # direto, pulando o router, a checagem tem que ser feita aqui, senão
    # qualquer membro (até viewer/client) exporta tudo sem essa permissão.
    ctx.require("sample:read")
    samples = await lims_service.list_samples(ctx, project_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_SAMPLE_CSV_HEADER)
    for s in samples:
        writer.writerow([
            s["code"], s["matrix"], s.get("treatment_group") or "",
            s.get("replicate") or "", s.get("lat") or "", s.get("lon") or "",
            s.get("notes") or "",
        ])
    return buf.getvalue()


async def import_samples_csv(ctx: Ctx, project_id: UUID, csv_text: str) -> dict[str, Any]:
    # Mesmo motivo do export: chama lims_service.create_sample direto, sem
    # passar pelo router de lims onde normalmente mora o ctx.require().
    ctx.require("sample:write")
    reader = csv.DictReader(io.StringIO(csv_text))
    missing = set(_SAMPLE_CSV_HEADER[:2]) - set(reader.fieldnames or [])
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Cabeçalho do CSV sem coluna(s) obrigatória(s): {sorted(missing)}.",
        )

    created = 0
    errors: list[SampleImportRowError] = []
    for i, raw_row in enumerate(reader, start=2):  # linha 1 é o header
        code = (raw_row.get("code") or "").strip()
        try:
            data = SampleCreate(
                code=code,
                matrix=raw_row["matrix"].strip(),
                treatment_group=(raw_row.get("treatment_group") or "").strip() or None,
                replicate=int(raw_row["replicate"]) if raw_row.get("replicate") else None,
                lat=float(raw_row["lat"]) if raw_row.get("lat") else None,
                lon=float(raw_row["lon"]) if raw_row.get("lon") else None,
                notes=(raw_row.get("notes") or "").strip() or None,
            )
            # SAVEPOINT por linha: uma falha (ex: código duplicado) não pode
            # abortar a transação inteira do request e derrubar as linhas
            # seguintes — o Postgres marca a transação como abortada até o
            # próximo ROLLBACK, sem savepoint isso destruiria o import inteiro
            # a partir da primeira linha ruim.
            async with ctx.session.begin_nested():
                await lims_service.create_sample(ctx, project_id, data)
            created += 1
        except HTTPException as exc:
            errors.append(SampleImportRowError(row=i, code=code or None, error=str(exc.detail)))
        except (ValueError, KeyError) as exc:
            errors.append(SampleImportRowError(row=i, code=code or None, error=f"linha inválida: {exc}"))

    return {"created": created, "errors": errors}
