"""Regras de identidade: login, organizações, membros, convites.

Duas conexões diferentes, de propósito — decisão de infraestrutura, não de
domínio, por isso permanece explícita aqui (não no repository):

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
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.security import create_access_token
from app.modules.identity.domain.entities import (
    Invitation,
    Organization,
    assert_email_domain_allowed,
)
from app.modules.identity.domain.exceptions import (
    AlreadyMemberError,
    DomainNotAllowedError,
    DuplicateInvitationError,
    SlugTakenError,
)
from app.modules.identity.oauth import OAuthProvider
from app.modules.identity.repository import PgIdentityRepository
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
from app.shared.context import Ctx
from app.shared.ids import new_id
from app.shared.tenancy import bind_tenant

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


def _user_out(user) -> UserOut:
    return UserOut(**user.to_dict())


def _org_out(membership) -> OrganizationOut:
    return OrganizationOut(
        id=membership.id, slug=membership.slug, name=membership.name, role=membership.role,
        role_labels=membership.role_labels,
    )


# ── 1. Login via Google ─────────────────────────────────────────────────────


async def login_with_google(body: GoogleLoginIn, provider: OAuthProvider) -> LoginOut:
    """`provider` é injetado pelo router (Depends(get_oauth_provider)), não
    instanciado aqui — é essa inversão que permite trocar de provedor OAuth
    sem tocar nesta função. O nome continua "login_with_google" porque é a
    única rota que existe hoje (`/auth/google`); quando existir um segundo
    provedor, generalizar o nome junto da rota nova."""
    try:
        claims = await provider.verify(body.access_token)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"Token do provedor OAuth inválido: {exc}"
        ) from exc

    email = claims.email
    if not email:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Provedor OAuth não retornou e-mail para este token."
        )

    try:
        assert_email_domain_allowed(email, settings.allowed_email_domain)
    except DomainNotAllowedError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))

    name = claims.name
    google_sub = claims.sub
    avatar_url = claims.avatar_url
    now = datetime.now(timezone.utc)

    async with system_sessionmaker()() as s:
        async with s.begin():
            repo = PgIdentityRepository(s)
            existing = await repo.find_user_by_email(email)

            if existing is None:
                # Usuário novo: só entra com convite pendente. Sem isso, qualquer
                # pessoa do domínio criaria conta sozinha.
                invite = await repo.find_pending_invitation(email)
                if invite is None:
                    # Bootstrap: instalação nova, zero organizações no sistema
                    # inteiro — não existe admin nenhum pra convidar ninguém, e
                    # exigir convite aqui travaria o primeiro login pra sempre
                    # (era exatamente o buraco que o v1, morto, tapava sozinho
                    # com "primeiro usuário vira admin"; nunca foi portado pro
                    # v2). Só vale a primeira vez: assim que a org #1 existir,
                    # cai de novo na exigência normal de convite.
                    if await repo.count_organizations() == 0:
                        user_id = await repo.create_user(
                            email=email, name=name, google_sub=google_sub,
                            avatar_url=avatar_url, at=now,
                        )
                        org = await repo.create_organization(
                            Organization(id=new_id(), slug="default", name=f"Organização de {name}")
                        )
                        await repo.add_member(org.id, user_id, "org_admin")
                    else:
                        raise HTTPException(
                            status.HTTP_403_FORBIDDEN,
                            "NotInvited: este e-mail não possui convite pendente. "
                            "Peça a um administrador que envie um convite.",
                        )
                else:
                    user_id = await repo.create_user(
                        email=email, name=name, google_sub=google_sub, avatar_url=avatar_url, at=now
                    )
                    await repo.accept_invitation(invite, user_id, now)
            else:
                user_id = existing.id
                await repo.touch_login(
                    user_id, at=now, google_sub=google_sub, avatar_url=avatar_url
                )
                # Usuário já existente pode ter sido convidado para uma org nova.
                for invite in await repo.list_pending_invitations(email):
                    await repo.accept_invitation(invite, user_id, now)

            user = await repo.get_user(user_id)
            orgs = await repo.orgs_of_user(user_id)

    # O papel do JWT é o da primeira org. Trocar de org emite token novo — o
    # papel nunca é escolhido pelo cliente.
    role = orgs[0].role if orgs else "viewer"
    token = create_access_token(sub=str(user_id), role=role)
    return LoginOut(
        access_token=token,
        user=_user_out(user),
        organizations=[_org_out(o) for o in orgs],
    )


# ── 2. /me ──────────────────────────────────────────────────────────────────


async def get_me(ctx: Ctx) -> MeOut:
    repo = PgIdentityRepository(ctx.session)
    user = await repo.get_user(ctx.user_id)
    orgs = await repo.orgs_of_user(ctx.user_id)
    current = next((o for o in orgs if o.id == ctx.org_id), None)
    return MeOut(
        user=_user_out(user),
        organization=_org_out(current) if current else None,
        role=ctx.role,
        organizations=[_org_out(o) for o in orgs],
    )


# ── 3 e 4. Organizações ─────────────────────────────────────────────────────


async def list_organizations(session: AsyncSession, user_id: UUID) -> list[OrganizationOut]:
    """Só enxerga as próprias — garantido pela policy `own_memberships`."""
    repo = PgIdentityRepository(session)
    return [_org_out(o) for o in await repo.orgs_of_user(user_id)]


async def create_organization(
    session: AsyncSession, user_id: UUID, body: OrganizationCreate
) -> OrganizationOut:
    """Cria a org e põe o criador como org_admin.

    É por aqui que a PRIMEIRA organização nasce: o usuário ainda não é membro de
    nada, então este endpoint não pode exigir `get_ctx`.
    """
    repo = PgIdentityRepository(session)
    org = Organization(id=new_id(), slug=body.slug, name=body.name, cnpj=body.cnpj)
    try:
        await repo.create_organization(org)
    except SlugTakenError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    # organization_members tem RLS com WITH CHECK sobre o GUC de tenant. Sem
    # amarrar a transação à org recém-criada, o próprio INSERT seria recusado.
    await bind_tenant(session, org.id, user_id)
    await repo.add_member(org.id, user_id, "org_admin")
    return OrganizationOut(id=org.id, slug=org.slug, name=org.name, role="org_admin")


# ── 5. Membros ──────────────────────────────────────────────────────────────


async def list_members(ctx: Ctx) -> list[MemberOut]:
    repo = PgIdentityRepository(ctx.session)
    return [MemberOut(**m) for m in await repo.list_members(ctx.org_id)]


# ── 6 e 7. Convites ─────────────────────────────────────────────────────────


async def create_invitation(ctx: Ctx, body: InvitationCreate) -> InvitationOut:
    email = body.email.strip().lower()
    try:
        assert_email_domain_allowed(email, settings.allowed_email_domain)
    except DomainNotAllowedError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Só é possível convidar e-mails do domínio {settings.allowed_email_domain}.",
        )

    repo = PgIdentityRepository(ctx.session)
    invitation = Invitation(
        id=new_id(),
        organization_id=ctx.org_id,
        email=email,
        role=body.role,
        invited_by=ctx.user_id,
    )
    try:
        saved = await repo.create_invitation(invitation)
    except AlreadyMemberError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except DuplicateInvitationError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return InvitationOut(**saved.to_dict())


async def list_invitations(ctx: Ctx) -> list[InvitationOut]:
    repo = PgIdentityRepository(ctx.session)
    return [InvitationOut(**i.to_dict()) for i in await repo.list_invitations(ctx.org_id)]


async def revoke_invitation(ctx: Ctx, invitation_id: UUID) -> None:
    repo = PgIdentityRepository(ctx.session)
    if not await repo.revoke_invitation(ctx.org_id, invitation_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Convite não encontrado, já aceito, ou de outra organização.",
        )


async def update_member_role(ctx: Ctx, user_id: UUID, role: str) -> None:
    if user_id == ctx.user_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Não é possível alterar o próprio papel por aqui — peça a outro "
            "administrador.",
        )
    repo = PgIdentityRepository(ctx.session)
    if not await repo.update_member_role(ctx.org_id, user_id, role):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membro não encontrado nesta organização.")


async def remove_member(ctx: Ctx, user_id: UUID) -> None:
    if user_id == ctx.user_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Não é possível remover a própria filiação por aqui — peça a "
            "outro administrador.",
        )
    repo = PgIdentityRepository(ctx.session)
    if not await repo.remove_member(ctx.org_id, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membro não encontrado nesta organização.")


# ── 8. Rótulos de papel por organização ──────────────────────────────────────


async def update_role_labels(ctx: Ctx, role_labels: list[dict[str, str]]) -> None:
    """Só org_admin — é configuração da organização inteira, não de um
    membro. Cada entrada é {"label": ..., "role": ...}; vários rótulos
    podem apontar pro mesmo papel técnico. O papel em si (VALID_ROLES) já
    foi validado no schema; aqui só falta persistir."""
    if ctx.role != "org_admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Só um administrador da organização pode configurar rótulos de papel.",
        )
    repo = PgIdentityRepository(ctx.session)
    await repo.update_role_labels(ctx.org_id, role_labels)
