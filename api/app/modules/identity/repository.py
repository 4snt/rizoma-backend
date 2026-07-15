"""Persistência de identidade. Todo `sqlalchemy.text()` do módulo mora aqui —
`service.py` só orquestra entidades (e a escolha de qual sessão/engine usar,
que é infraestrutura, não domínio).
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.domain.entities import (
    Invitation,
    Organization,
    OrganizationMembership,
    User,
)
from app.modules.identity.domain.exceptions import (
    AlreadyMemberError,
    DuplicateInvitationError,
    SlugTakenError,
)
from app.shared.ids import new_id

_ORGS_OF_USER = text(
    """
    SELECT o.id, o.slug, o.name, m.role
      FROM organization_members m
      JOIN organizations o ON o.id = m.organization_id
     WHERE m.user_id = :u AND o.is_active
     ORDER BY m.created_at
    """
)


class PgIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Usuários ──────────────────────────────────────────────────────────
    async def find_user_by_email(self, email: str) -> User | None:
        row = (
            await self.session.execute(
                text(
                    "SELECT id, email, name, avatar_url, is_active, last_login, google_sub "
                    "FROM users WHERE email = :e"
                ),
                {"e": email},
            )
        ).mappings().first()
        return User(**dict(row)) if row is not None else None

    async def get_user(self, user_id: UUID) -> User | None:
        row = (
            await self.session.execute(
                text(
                    "SELECT id, email, name, avatar_url, is_active, last_login, google_sub "
                    "FROM users WHERE id = :u"
                ),
                {"u": str(user_id)},
            )
        ).mappings().first()
        return User(**dict(row)) if row is not None else None

    async def create_user(
        self, *, email: str, name: str, google_sub: str | None, avatar_url: str | None, at: datetime
    ) -> UUID:
        user_id = new_id()
        await self.session.execute(
            text(
                "INSERT INTO users (id, email, name, google_sub, avatar_url, last_login) "
                "VALUES (:id, :e, :n, :g, :a, :t)"
            ),
            {
                "id": str(user_id),
                "e": email,
                "n": name,
                "g": google_sub,
                "a": avatar_url,
                "t": at,
            },
        )
        return user_id

    async def touch_login(
        self, user_id: UUID, *, at: datetime, google_sub: str | None, avatar_url: str | None
    ) -> None:
        await self.session.execute(
            text(
                "UPDATE users SET last_login = :t, "
                "google_sub = COALESCE(google_sub, :g), "
                "avatar_url = COALESCE(:a, avatar_url) WHERE id = :u"
            ),
            {"t": at, "g": google_sub, "a": avatar_url, "u": str(user_id)},
        )

    # ── Organizações ──────────────────────────────────────────────────────
    async def orgs_of_user(self, user_id: UUID) -> list[OrganizationMembership]:
        """Só enxerga as próprias — garantido pela policy `own_memberships`."""
        rows = (await self.session.execute(_ORGS_OF_USER, {"u": str(user_id)})).mappings().all()
        return [OrganizationMembership(**dict(r)) for r in rows]

    async def create_organization(self, org: Organization) -> Organization:
        try:
            await self.session.execute(
                text(
                    "INSERT INTO organizations (id, slug, name, cnpj) VALUES (:id, :s, :n, :c)"
                ),
                {"id": str(org.id), "s": org.slug, "n": org.name, "c": org.cnpj},
            )
            await self.session.flush()
        except IntegrityError as exc:
            raise SlugTakenError(
                f"Já existe uma organização com o slug '{org.slug}'."
            ) from exc
        return org

    async def add_member(self, organization_id: UUID, user_id: UUID, role: str) -> None:
        await self.session.execute(
            text(
                "INSERT INTO organization_members (id, organization_id, user_id, role) "
                "VALUES (:id, :o, :u, :r) ON CONFLICT (organization_id, user_id) DO NOTHING"
            ),
            {"id": str(new_id()), "o": str(organization_id), "u": str(user_id), "r": role},
        )

    async def list_members(self, organization_id: UUID) -> list[dict]:
        rows = (
            await self.session.execute(
                text(
                    "SELECT m.id, m.user_id, u.email, u.name, m.role, m.created_at "
                    "FROM organization_members m JOIN users u ON u.id = m.user_id "
                    "WHERE m.organization_id = :o ORDER BY m.created_at"
                ),
                {"o": str(organization_id)},
            )
        ).mappings().all()
        return [dict(r) for r in rows]

    async def member_exists(self, organization_id: UUID, email: str) -> bool:
        row = (
            await self.session.execute(
                text(
                    "SELECT 1 FROM organization_members m JOIN users u ON u.id = m.user_id "
                    "WHERE m.organization_id = :o AND lower(u.email) = :e"
                ),
                {"o": str(organization_id), "e": email},
            )
        ).first()
        return row is not None

    # ── Convites ──────────────────────────────────────────────────────────
    async def find_pending_invitation(self, email: str) -> Invitation | None:
        row = (
            await self.session.execute(
                text(
                    "SELECT id, organization_id, email, role, invited_by, invited_at, accepted_at "
                    "FROM invitations WHERE lower(email) = :e AND accepted_at IS NULL "
                    "ORDER BY invited_at LIMIT 1"
                ),
                {"e": email},
            )
        ).mappings().first()
        return Invitation(**dict(row)) if row is not None else None

    async def list_pending_invitations(self, email: str) -> list[Invitation]:
        rows = (
            await self.session.execute(
                text(
                    "SELECT id, organization_id, email, role, invited_by, invited_at, accepted_at "
                    "FROM invitations WHERE lower(email) = :e AND accepted_at IS NULL"
                ),
                {"e": email},
            )
        ).mappings().all()
        return [Invitation(**dict(r)) for r in rows]

    async def accept_invitation(self, invitation: Invitation, user_id: UUID, at: datetime) -> None:
        """Aceitar um convite é um único movimento: a filiação nasce E o
        convite é marcado aceito — nunca um sem o outro."""
        await self.add_member(invitation.organization_id, user_id, invitation.role)
        await self.session.execute(
            text("UPDATE invitations SET accepted_at = :t WHERE id = :i"),
            {"t": at, "i": str(invitation.id)},
        )

    async def create_invitation(self, invitation: Invitation) -> Invitation:
        if await self.member_exists(invitation.organization_id, invitation.email):
            raise AlreadyMemberError(f"{invitation.email} já é membro desta organização.")
        try:
            row = (
                await self.session.execute(
                    text(
                        "INSERT INTO invitations (id, organization_id, email, role, invited_by) "
                        "VALUES (:id, :o, :e, :r, :b) "
                        "RETURNING id, organization_id, email, role, invited_by, "
                        "invited_at, accepted_at"
                    ),
                    {
                        "id": str(invitation.id),
                        "o": str(invitation.organization_id),
                        "e": invitation.email,
                        "r": invitation.role,
                        "b": str(invitation.invited_by) if invitation.invited_by else None,
                    },
                )
            ).mappings().first()
        except IntegrityError as exc:
            raise DuplicateInvitationError(
                f"Já existe um convite para {invitation.email} nesta organização."
            ) from exc
        return Invitation(**dict(row))

    async def list_invitations(self, organization_id: UUID) -> list[Invitation]:
        rows = (
            await self.session.execute(
                text(
                    "SELECT id, organization_id, email, role, invited_by, invited_at, "
                    "accepted_at FROM invitations WHERE organization_id = :o "
                    "ORDER BY invited_at DESC"
                ),
                {"o": str(organization_id)},
            )
        ).mappings().all()
        return [Invitation(**dict(r)) for r in rows]
