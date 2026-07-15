"""Regras de negócio dos laudos.

Camada de aplicação: orquestra `repository.py` (persistência do agregado
Laudo), `snapshot.py` (leitura cross-módulo) e `domain/entities.py`
(invariantes: laudo publicado é imutável, hash de verificação). Não fala SQL
sobre a tabela `reports` diretamente — isso é `repository.py`.

O dual-engine de `/verify` (papel `rizoma_system`, BYPASSRLS) é decisão de
infraestrutura, não de domínio — permanece explícito aqui, como no módulo
`identity` (mesma razão: é a única leitura legitimamente cross-organização).
"""
import hashlib
from datetime import datetime, timezone
from functools import lru_cache
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings
from app.modules.reports import snapshot as snapshot_reader
from app.modules.reports.domain.entities import Report, content_hash
from app.modules.reports.domain.exceptions import AlreadyPublishedError
from app.modules.reports.pdf import build_report_pdf
from app.modules.reports.repository import PgReportRepository
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


async def create_report(ctx: Ctx, project_id: UUID, data) -> dict:
    ctx.require("report:write")
    repo = PgReportRepository(ctx.session)

    content = await snapshot_reader.build_snapshot(ctx, project_id, data.title)
    code = data.code or f"LAU-{content['project']['code']}"
    next_version = await repo.next_version_for_code(code)

    report = Report(
        id=new_id(),
        organization_id=ctx.org_id,
        project_id=project_id,
        code=code,
        version=next_version,
        title=data.title,
        status="draft",
        content=content,
        created_by=ctx.user_id,
    )
    await repo.create(report)
    return await get_report(ctx, report.id, permission="report:write")


async def get_report(ctx: Ctx, report_id: UUID, permission: str = "report:read") -> dict:
    ctx.require(permission)
    repo = PgReportRepository(ctx.session)
    report = await repo.get(report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Laudo não encontrado.")
    download_url = (
        presign_download(report.storage_key)
        if report.status == "published" and report.storage_key
        else None
    )
    return report.to_dict(download_url=download_url)


async def list_reports(ctx: Ctx, project_id: UUID) -> list[dict]:
    ctx.require("report:read")
    repo = PgReportRepository(ctx.session)
    reports = await repo.list_by_project(project_id)
    return [r.to_list_item() for r in reports]


async def sign_report(ctx: Ctx, report_id: UUID, base_url: str) -> dict:
    """Gera o PDF, calcula o hash, guarda no MinIO e publica.

    A ordem importa: o QR precisa da URL de verificação, que precisa de um
    hash que exista ANTES do PDF. Por isso o QR carrega o hash do CONTEÚDO —
    o hash do arquivo só existe depois que o arquivo existe.
    """
    ctx.require("report:sign")
    repo = PgReportRepository(ctx.session)

    report = await repo.get(report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Laudo não encontrado.")

    try:
        report.assert_can_be_signed()
    except AlreadyPublishedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))

    signer = (
        await ctx.session.execute(
            text("SELECT name FROM users WHERE id = :u"), {"u": str(ctx.user_id)}
        )
    ).scalar_one_or_none()

    content = dict(report.content or {})
    signed_at = datetime.now(timezone.utc)
    content["signed_by_name"] = signer
    content["signed_at"] = signed_at.isoformat()
    content["content_sha256"] = content_hash(content)

    verify_url = (
        f"{base_url.rstrip('/')}/api/v2/reports/{report_id}/verify"
        f"?hash={content['content_sha256']}"
    )

    pdf_bytes = build_report_pdf(content, report.code, report.version, verify_url)
    pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()

    storage_key = f"org/{ctx.org_id}/reports/{report.code}_v{report.version}_{report_id}.pdf"
    ensure_bucket()
    internal_client().put_object(
        Bucket=settings.s3_bucket,
        Key=storage_key,
        Body=pdf_bytes,
        ContentType="application/pdf",
    )

    await repo.sign(
        report_id,
        content=content,
        storage_key=storage_key,
        sha256=pdf_sha,
        signed_by=ctx.user_id,
        signed_at=signed_at,
    )
    return await get_report(ctx, report_id, permission="report:sign")


async def verify_report(report_id: UUID, provided_hash: str | None) -> dict:
    """PÚBLICO e sem autenticação — é o destino do QR Code.

    Devolve o MÍNIMO: se o documento é autêntico e de quem. Nada de
    resultados, cliente ou amostras: qualquer pessoa do planeta pode chamar
    isto.
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

    report = Report(
        id=report_id,
        organization_id=None,
        project_id=None,
        code=row.code,
        version=row.version,
        title="",
        status=row.status,
        content=row.content or {},
        sha256=row.sha256,
    )
    if not report.matches_hash(provided_hash):
        return invalid

    return {
        "valid": True,
        "code": row.code,
        "version": row.version,
        "project": row.project_name,
        "signed_at": row.signed_at,
        "organization": row.org_name,
    }
