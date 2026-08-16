"""Persistência de webhooks. Import/export de amostras não tem repository
próprio — reaproveita `app.modules.lims.service` (é composição de casos de
uso já existentes, não uma tabela nova)."""
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_WEBHOOK_COLS = "id, organization_id, url, event_types, is_active, created_by, created_at"
# secret só sai no RETURNING do create — é a única vez que o dono vê o valor.
_WEBHOOK_COLS_WITH_SECRET = _WEBHOOK_COLS.replace("url,", "url, secret,")


class PgWebhookRepository:
    """Usada em dois contextos: sessão com tenant (Ctx, CRUD do usuário) e
    sessão system/BYPASSRLS (dispatch de evento, cross-org por natureza —
    filtra por organization_id explícito na query, RLS não entra em jogo)."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(
        self, id_: UUID, organization_id: UUID, url: str, event_types: list[str],
        secret: str, created_by: UUID | None,
    ) -> dict:
        row = (
            await self._s.execute(
                text(
                    f"INSERT INTO webhook_subscriptions "
                    "(id, organization_id, url, event_types, secret, created_by) "
                    "VALUES (:id, :org, :url, :events, :secret, :created_by) "
                    f"RETURNING {_WEBHOOK_COLS_WITH_SECRET}"
                ),
                {
                    "id": str(id_), "org": str(organization_id), "url": url,
                    "events": event_types, "secret": secret,
                    "created_by": str(created_by) if created_by else None,
                },
            )
        ).mappings().one()
        return dict(row)

    async def list_for_org(self, organization_id: UUID) -> list[dict]:
        rows = (
            await self._s.execute(
                text(f"SELECT {_WEBHOOK_COLS} FROM webhook_subscriptions WHERE organization_id = :org ORDER BY created_at"),
                {"org": str(organization_id)},
            )
        ).mappings().all()
        return [dict(r) for r in rows]

    async def delete(self, id_: UUID, organization_id: UUID) -> bool:
        result = await self._s.execute(
            text("DELETE FROM webhook_subscriptions WHERE id = :id AND organization_id = :org"),
            {"id": str(id_), "org": str(organization_id)},
        )
        return result.rowcount > 0

    async def active_for_event(self, organization_id: UUID, event_type: str) -> list[dict]:
        """Cross-org na origem (chamado com sessão rizoma_system) — filtra
        por organization_id explícito, não por RLS."""
        rows = (
            await self._s.execute(
                text(
                    "SELECT id, url, secret FROM webhook_subscriptions "
                    "WHERE organization_id = :org AND is_active = true "
                    "AND :event = ANY(event_types)"
                ),
                {"org": str(organization_id), "event": event_type},
            )
        ).mappings().all()
        return [dict(r) for r in rows]
