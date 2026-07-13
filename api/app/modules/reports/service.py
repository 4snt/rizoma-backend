"""Regras de domínio dos laudos.

Um laudo é um **snapshot**, não uma view. O `content` congela o que era verdade
no momento da emissão — se um resultado for corrigido depois, o laudo já assinado
continua dizendo o que dizia, e a correção exige um laudo NOVO. Um laudo que
"se atualiza sozinho" é um laudo que não prova nada.

Sobre os dois hashes (ver também `pdf.py`):
  - `content_sha256` — hash do snapshot JSON. Impresso no PDF e carregado no QR.
    Existe ANTES da renderização, então pode estar dentro do documento.
  - `reports.sha256`  — hash do ARQUIVO PDF. Não pode estar dentro do próprio PDF
    (imprimir o hash mudaria o hash).
`/verify` aceita os dois: ambos identificam unicamente o mesmo laudo emitido.
"""
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings
from app.modules.reports.pdf import build_report_pdf
from app.shared.context import Ctx
from app.shared.ids import new_id
from app.shared.storage import ensure_bucket, internal_client, presign_download

# ── Engine de sistema (BYPASSRLS) ───────────────────────────────────────
# /verify é público e cross-organização: quem escaneia o QR não tem token e não
# pertence a organização nenhuma. Isso NÃO é motivo para inventar um GUC de
# bypass (qualquer um poderia setá-lo via SQL injetado). Cross-org legítimo usa o
# PAPEL rizoma_system, cujo BYPASSRLS é atributo do banco e não se auto-concede.


@lru_cache(maxsize=1)
def system_engine() -> AsyncEngine:
    dsn = (
        f"postgresql+asyncpg://rizoma_system:rizoma_system_pw"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )
    return create_async_engine(dsn, pool_size=2, max_overflow=2, pool_pre_ping=True)


async def dispose_system_engine() -> None:
    """As conexões ficam presas ao event loop que as abriu; nos testes, cada caso
    roda em um loop novo. Sem descartar, o asyncpg estoura."""
    engine = system_engine.cache_info().currsize and system_engine()
    if engine:
        await engine.dispose()
    system_engine.cache_clear()


def _jsonable(value):
    """Snapshot precisa virar JSON puro: Decimal e datetime não são serializáveis.

    Decimal vira STRING, não float: 0.05 em float binário não é 0.05, e um laudo
    não pode perder precisão na serialização.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _content_hash(content: dict) -> str:
    """Hash canônico do snapshot: chaves ordenadas, sem o próprio campo de hash."""
    payload = {k: v for k, v in content.items() if k != "content_sha256"}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _build_snapshot(ctx: Ctx, project_id: UUID, title: str) -> dict:
    s = ctx.session

    project = (
        await s.execute(
            text(
                "SELECT p.id, p.code, p.name, p.description, p.marker_type, p.status, "
                "       p.customer_id, o.name AS org_name, o.cnpj AS org_cnpj "
                "FROM projects p JOIN organizations o ON o.id = p.organization_id "
                "WHERE p.id = :p"
            ),
            {"p": str(project_id)},
        )
    ).first()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Projeto não encontrado.")

    customer = None
    if project.customer_id:
        customer = (
            await s.execute(
                text(
                    "SELECT name, document, contact_email, contact_phone "
                    "FROM customers WHERE id = :c"
                ),
                {"c": str(project.customer_id)},
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

    # Bioinformática: SELECT direto (o módulo jobs é de outro agente — acoplar os
    # dois por import criaria dependência circular entre fatias).
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

    def _summarize(data) -> str:
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
                "document": customer.document,
                "contact_email": customer.contact_email,
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
    return _jsonable(content)


async def create_report(ctx: Ctx, project_id: UUID, data) -> dict:
    ctx.require("report:write")
    s = ctx.session

    content = await _build_snapshot(ctx, project_id, data.title)
    code = data.code or f"LAU-{content['project']['code']}"

    # UNIQUE(organization_id, code, version): reemitir com o mesmo código gera a
    # versão seguinte em vez de estourar conflito.
    nxt = (
        await s.execute(
            text("SELECT COALESCE(MAX(version), 0) + 1 FROM reports WHERE code = :c"),
            {"c": code},
        )
    ).scalar_one()

    report_id = new_id()
    await s.execute(
        text(
            """
            INSERT INTO reports (
                id, organization_id, project_id, code, version, title, status,
                content, created_by
            ) VALUES (
                :i, :o, :p, :c, :v, :t, 'draft', CAST(:content AS jsonb), :cb
            )
            """
        ),
        {
            "i": str(report_id),
            "o": str(ctx.org_id),
            "p": str(project_id),
            "c": code,
            "v": nxt,
            "t": data.title,
            "content": json.dumps(content, ensure_ascii=False),
            "cb": str(ctx.user_id),
        },
    )
    return await get_report(ctx, report_id, permission="report:write")


async def _require_report(ctx: Ctx, report_id: UUID):
    row = (
        await ctx.session.execute(
            text(
                "SELECT id, project_id, code, version, title, status, content, "
                "storage_key, sha256, signed_by, signed_at, created_at "
                "FROM reports WHERE id = :i"
            ),
            {"i": str(report_id)},
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Laudo não encontrado.")
    return row


async def get_report(ctx: Ctx, report_id: UUID, permission: str = "report:read") -> dict:
    ctx.require(permission)
    row = await _require_report(ctx, report_id)
    out = dict(row._mapping)
    out["download_url"] = (
        presign_download(row.storage_key)
        if row.status == "published" and row.storage_key
        else None
    )
    return out


async def list_reports(ctx: Ctx, project_id: UUID) -> list[dict]:
    ctx.require("report:read")
    rows = (
        await ctx.session.execute(
            text(
                "SELECT id, project_id, code, version, title, status, sha256, "
                "signed_at, created_at FROM reports "
                "WHERE project_id = :p ORDER BY created_at DESC"
            ),
            {"p": str(project_id)},
        )
    ).fetchall()
    return [dict(r._mapping) for r in rows]


async def sign_report(ctx: Ctx, report_id: UUID, base_url: str) -> dict:
    """Gera o PDF, calcula o hash, guarda no MinIO e publica.

    A ordem importa: o QR precisa da URL de verificação, que precisa de um hash
    que exista ANTES do PDF. Por isso o QR carrega o hash do CONTEÚDO — o hash do
    arquivo só existe depois que o arquivo existe.
    """
    ctx.require("report:sign")
    s = ctx.session
    row = await _require_report(ctx, report_id)

    if row.status == "published":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Laudo já publicado. Um laudo assinado é imutável — emita uma versão nova.",
        )

    signer = (
        await s.execute(
            text("SELECT name FROM users WHERE id = :u"), {"u": str(ctx.user_id)}
        )
    ).scalar_one_or_none()

    content = dict(row.content or {})
    signed_at = datetime.now(timezone.utc)
    content["signed_by_name"] = signer
    content["signed_at"] = signed_at.isoformat()
    content["content_sha256"] = _content_hash(content)

    verify_url = (
        f"{base_url.rstrip('/')}/api/v2/reports/{report_id}/verify"
        f"?hash={content['content_sha256']}"
    )

    pdf_bytes = build_report_pdf(content, row.code, row.version, verify_url)
    pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()

    storage_key = f"org/{ctx.org_id}/reports/{row.code}_v{row.version}_{report_id}.pdf"
    ensure_bucket()
    internal_client().put_object(
        Bucket=settings.s3_bucket,
        Key=storage_key,
        Body=pdf_bytes,
        ContentType="application/pdf",
    )

    await s.execute(
        text(
            """
            UPDATE reports SET
                content = CAST(:content AS jsonb),
                storage_key = :k,
                sha256 = :h,
                signed_by = :sb,
                signed_at = :sa,
                status = 'published'
            WHERE id = :i
            """
        ),
        {
            "content": json.dumps(content, ensure_ascii=False),
            "k": storage_key,
            "h": pdf_sha,
            "sb": str(ctx.user_id),
            "sa": signed_at,
            "i": str(report_id),
        },
    )
    return await get_report(ctx, report_id, permission="report:sign")


async def verify_report(report_id: UUID, provided_hash: str | None) -> dict:
    """PÚBLICO e sem autenticação — é o destino do QR Code.

    Devolve o MÍNIMO: se o documento é autêntico e de quem. Nada de resultados,
    cliente ou amostras: qualquer pessoa do planeta pode chamar isto.
    """
    invalid = {"valid": False, "detail": "Laudo não encontrado ou hash não confere."}
    if not provided_hash:
        return {"valid": False, "detail": "Informe o parâmetro ?hash=<sha256>."}

    async with system_engine().connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT r.code, r.version, r.status, r.sha256, r.signed_at, "
                    "       r.content, p.name AS project_name, o.name AS org_name "
                    "FROM reports r "
                    "JOIN projects p ON p.id = r.project_id "
                    "JOIN organizations o ON o.id = r.organization_id "
                    "WHERE r.id = :i"
                ),
                {"i": str(report_id)},
            )
        ).first()

    if row is None or row.status != "published":
        return invalid

    content = row.content or {}
    accepted = {row.sha256, content.get("content_sha256")} - {None}
    if provided_hash.strip().lower() not in {h.lower() for h in accepted}:
        return invalid

    return {
        "valid": True,
        "code": row.code,
        "version": row.version,
        "project": row.project_name,
        "signed_at": row.signed_at,
        "organization": row.org_name,
    }
