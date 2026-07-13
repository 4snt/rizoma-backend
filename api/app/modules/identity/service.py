"""Regras de identidade: login, organizações, membros, convites.

Duas conexões diferentes, de propósito:

  * A sessão do request (papel `rizoma_app`, NOBYPASSRLS) para tudo que acontece
    DENTRO de uma organização já conhecida. A RLS é a rede de segurança.

  * Um engine de sistema (papel `rizoma_system`, BYPASSRLS) SÓ para o login. No
    momento do login ainda não existe organização: o usuário está provando quem
    é, e para descobrir a que org ele pertence é preciso ler `invitations` de
    todas elas. Não há GUC de tenant possível aí. É a única brecha legítima —
    por isso mora numa função só, e não num bypass genérico (ver tenancy.py).
"""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.google_auth import verify_google_token
from app.core.security import create_access_token
from app.shared.context import Ctx
from app.shared.ids import new_id
from app.shared.tenancy import bind_tenant
from app.modules.identity.schemas import (
    GoogleLoginIn,
    InvitationCreate,
    InvitationOut,
    LoginOut,
    MemberOut,
    MeOut,
    OrganizationCreate,
    OrganizationOut,
    UserOut,
)

# ── Engine de sistema (BYPASSRLS) ───────────────────────────────────────────
# Usado só no login: é o único momento sem org definida, em que é preciso ler
# invitations de todas as orgs. Credenciais no `settings` (papel criado na 0001).
_system_engine_instance: AsyncEngine | None = None
_system_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _system_dsn() -> str:
    return (
        f"postgresql+asyncpg://{settings.system_db_user}:{settings.system_db_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


def system_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _system_engine_instance, _system_sessionmaker
    if _system_sessionmaker is None:
        _system_engine_instance = create_async_engine(
            _system_dsn(), pool_size=2, max_overflow=2, pool_pre_ping=True
        )
        _system_sessionmaker = async_sessionmaker(
            _system_engine_instance, expire_on_commit=False, class_=AsyncSession
        )
    return _system_sessionmaker


async def dispose_system_engine() -> None:
    global _system_engine_instance, _system_sessionmaker
    if _system_engine_instance is not None:
        await _system_engine_instance.dispose()
    _system_engine_instance = None
    _system_sessionmaker = None


# ── Consultas reusadas ──────────────────────────────────────────────────────

_ORGS_OF_USER = text(
    """
    SELECT o.id, o.slug, o.name, m.role
      FROM organization_members m
      JOIN organizations o ON o.id = m.organization_id
     WHERE m.user_id = :u AND o.is_active
     ORDER BY m.created_at
    """
)


async def _orgs_of_user(session: AsyncSession, user_id: UUID) -> list[OrganizationOut]:
    rows = (await session.execute(_ORGS_OF_USER, {"u": str(user_id)})).mappings().all()
    return [OrganizationOut(**r) for r in rows]


async def _user_out(session: AsyncSession, user_id: UUID) -> UserOut:
    row = (
        await session.execute(
            text(
                "SELECT id, email, name, avatar_url, is_active, last_login "
                "FROM users WHERE id = :u"
            ),
            {"u": str(user_id)},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado.")
    return UserOut(**row)


# ── 1. Login via Google ─────────────────────────────────────────────────────


async def login_with_google(body: GoogleLoginIn) -> LoginOut:
    try:
        claims = await verify_google_token(body.access_token, settings.google_client_id)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"Token do Google inválido: {exc}"
        ) from exc

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Google não retornou e-mail para este token."
        )

    domain = settings.allowed_email_domain
    if domain and not email.endswith(domain.lower()):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"DomainNotAllowed: acesso restrito a e-mails do domínio {domain}.",
        )

    name = claims.get("name") or email.split("@")[0]
    google_sub = claims.get("sub")
    avatar_url = claims.get("picture")
    now = datetime.now(timezone.utc)

    async with system_sessionmaker()() as s:
        async with s.begin():
            row = (
                await s.execute(
                    text("SELECT id FROM users WHERE email = :e"), {"e": email}
                )
            ).first()

            if row is None:
                # Usuário novo: só entra com convite pendente. Sem isso, qualquer
                # pessoa do domínio criaria conta sozinha.
                invite = (
                    await s.execute(
                        text(
                            "SELECT id, organization_id, role FROM invitations "
                            "WHERE lower(email) = :e AND accepted_at IS NULL "
                            "ORDER BY invited_at LIMIT 1"
                        ),
                        {"e": email},
                    )
                ).mappings().first()
                if invite is None:
                    raise HTTPException(
                        status.HTTP_403_FORBIDDEN,
                        "NotInvited: este e-mail não possui convite pendente. "
                        "Peça a um administrador que envie um convite.",
                    )

                user_id = new_id()
                await s.execute(
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
                        "t": now,
                    },
                )
                await _accept_invitation(s, invite, user_id, now)
            else:
                user_id = row[0]
                await s.execute(
                    text(
                        "UPDATE users SET last_login = :t, "
                        "google_sub = COALESCE(google_sub, :g), "
                        "avatar_url = COALESCE(:a, avatar_url) WHERE id = :u"
                    ),
                    {"t": now, "g": google_sub, "a": avatar_url, "u": str(user_id)},
                )
                # Usuário já existente pode ter sido convidado para uma org nova.
                pending = (
                    await s.execute(
                        text(
                            "SELECT id, organization_id, role FROM invitations "
                            "WHERE lower(email) = :e AND accepted_at IS NULL"
                        ),
                        {"e": email},
                    )
                ).mappings().all()
                for invite in pending:
                    await _accept_invitation(s, invite, user_id, now)

            user = await _user_out(s, user_id)
            orgs = await _orgs_of_user(s, user_id)

    # O papel do JWT é o da primeira org. Trocar de org emite token novo — o
    # papel nunca é escolhido pelo cliente.
    role = orgs[0].role if orgs else "viewer"
    token = create_access_token(sub=str(user_id), role=role)
    return LoginOut(access_token=token, user=user, organizations=orgs)


async def _accept_invitation(
    s: AsyncSession, invite, user_id: UUID, now: datetime
) -> None:
    await s.execute(
        text(
            "INSERT INTO organization_members (id, organization_id, user_id, role) "
            "VALUES (:id, :o, :u, :r) ON CONFLICT (organization_id, user_id) DO NOTHING"
        ),
        {
            "id": str(new_id()),
            "o": str(invite["organization_id"]),
            "u": str(user_id),
            "r": invite["role"],
        },
    )
    await s.execute(
        text("UPDATE invitations SET accepted_at = :t WHERE id = :i"),
        {"t": now, "i": str(invite["id"])},
    )


# ── 2. /me ──────────────────────────────────────────────────────────────────


async def get_me(ctx: Ctx) -> MeOut:
    user = await _user_out(ctx.session, ctx.user_id)
    orgs = await _orgs_of_user(ctx.session, ctx.user_id)
    current = next((o for o in orgs if o.id == ctx.org_id), None)
    return MeOut(user=user, organization=current, role=ctx.role, organizations=orgs)


# ── 3 e 4. Organizações ─────────────────────────────────────────────────────


async def list_organizations(
    session: AsyncSession, user_id: UUID
) -> list[OrganizationOut]:
    """Só enxerga as próprias — garantido pela policy `own_memberships`."""
    return await _orgs_of_user(session, user_id)


async def create_organization(
    session: AsyncSession, user_id: UUID, body: OrganizationCreate
) -> OrganizationOut:
    """Cria a org e põe o criador como org_admin.

    É por aqui que a PRIMEIRA organização nasce: o usuário ainda não é membro de
    nada, então este endpoint não pode exigir `get_ctx`.
    """
    org_id = new_id()
    try:
        await session.execute(
            text(
                "INSERT INTO organizations (id, slug, name, cnpj) "
                "VALUES (:id, :s, :n, :c)"
            ),
            {"id": str(org_id), "s": body.slug, "n": body.name, "c": body.cnpj},
        )
        await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Já existe uma organização com o slug '{body.slug}'.",
        ) from exc

    # organization_members tem RLS com WITH CHECK sobre o GUC de tenant. Sem
    # amarrar a transação à org recém-criada, o próprio INSERT seria recusado.
    await bind_tenant(session, org_id, user_id)
    await session.execute(
        text(
            "INSERT INTO organization_members (id, organization_id, user_id, role) "
            "VALUES (:id, :o, :u, 'org_admin')"
        ),
        {"id": str(new_id()), "o": str(org_id), "u": str(user_id)},
    )
    return OrganizationOut(id=org_id, slug=body.slug, name=body.name, role="org_admin")


# ── 5. Membros ──────────────────────────────────────────────────────────────


async def list_members(ctx: Ctx) -> list[MemberOut]:
    rows = (
        await ctx.session.execute(
            text(
                "SELECT m.id, m.user_id, u.email, u.name, m.role, m.created_at "
                "FROM organization_members m JOIN users u ON u.id = m.user_id "
                "WHERE m.organization_id = :o ORDER BY m.created_at"
            ),
            {"o": str(ctx.org_id)},
        )
    ).mappings().all()
    return [MemberOut(**r) for r in rows]


# ── 6 e 7. Convites ─────────────────────────────────────────────────────────


async def create_invitation(ctx: Ctx, body: InvitationCreate) -> InvitationOut:
    email = body.email.strip().lower()
    domain = settings.allowed_email_domain
    if domain and not email.endswith(domain.lower()):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Só é possível convidar e-mails do domínio {domain}.",
        )

    already = (
        await ctx.session.execute(
            text(
                "SELECT 1 FROM organization_members m JOIN users u ON u.id = m.user_id "
                "WHERE m.organization_id = :o AND lower(u.email) = :e"
            ),
            {"o": str(ctx.org_id), "e": email},
        )
    ).first()
    if already:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{email} já é membro desta organização."
        )

    inv_id = new_id()
    try:
        row = (
            await ctx.session.execute(
                text(
                    "INSERT INTO invitations (id, organization_id, email, role, invited_by) "
                    "VALUES (:id, :o, :e, :r, :b) "
                    "RETURNING id, organization_id, email, role, invited_by, "
                    "invited_at, accepted_at"
                ),
                {
                    "id": str(inv_id),
                    "o": str(ctx.org_id),
                    "e": email,
                    "r": body.role,
                    "b": str(ctx.user_id),
                },
            )
        ).mappings().first()
    except IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Já existe um convite para {email} nesta organização.",
        ) from exc
    return InvitationOut(**row)


async def list_invitations(ctx: Ctx) -> list[InvitationOut]:
    rows = (
        await ctx.session.execute(
            text(
                "SELECT id, organization_id, email, role, invited_by, invited_at, "
                "accepted_at FROM invitations WHERE organization_id = :o "
                "ORDER BY invited_at DESC"
            ),
            {"o": str(ctx.org_id)},
        )
    ).mappings().all()
    return [InvitationOut(**r) for r in rows]
