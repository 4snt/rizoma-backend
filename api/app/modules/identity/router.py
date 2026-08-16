"""Endpoints de identidade. Montado pelo main.py em /api/v2/identity."""
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.modules.identity import service
from app.modules.identity.schemas import (
    GoogleLoginIn,
    InvitationCreate,
    InvitationOut,
    LoginOut,
    MemberOut,
    MemberRoleUpdate,
    MeOut,
    OrganizationCreate,
    OrganizationOut,
)
from app.shared.context import Ctx, get_ctx, get_session
from app.shared.tenancy import bind_user

router = APIRouter(tags=["identity"])

_bearer = HTTPBearer()


@dataclass(frozen=True)
class AuthUser:
    """Usuário autenticado que ainda NÃO escolheu organização.

    `get_ctx` exige um membership e devolve 403 sem ele — o que é correto para
    quase tudo, mas fecharia a porta justamente para quem vai criar a primeira
    organização. Daí esta dependência mais fraca: identidade sim, tenant não.
    """

    user_id: UUID
    session: AsyncSession


async def get_auth_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> AuthUser:
    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido ou expirado.")

    raw = payload.get("sub")
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token malformado.")

    await session.begin()
    # A policy `own_memberships` depende deste GUC para o usuário enxergar os
    # próprios vínculos enquanto nenhuma org está selecionada.
    await bind_user(session, UUID(raw))
    try:
        yield AuthUser(user_id=UUID(raw), session=session)
        await session.commit()
    except Exception:
        await session.rollback()
        raise


@router.post("/auth/google", response_model=LoginOut)
async def google_login(body: GoogleLoginIn) -> LoginOut:
    return await service.login_with_google(body)


@router.get("/me", response_model=MeOut)
async def me(ctx: Ctx = Depends(get_ctx)) -> MeOut:
    return await service.get_me(ctx)


@router.get("/organizations", response_model=list[OrganizationOut])
async def list_organizations(
    auth: AuthUser = Depends(get_auth_user),
) -> list[OrganizationOut]:
    return await service.list_organizations(auth.session, auth.user_id)


@router.post(
    "/organizations",
    response_model=OrganizationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization(
    body: OrganizationCreate, auth: AuthUser = Depends(get_auth_user)
) -> OrganizationOut:
    return await service.create_organization(auth.session, auth.user_id, body)


@router.get("/members", response_model=list[MemberOut])
async def list_members(ctx: Ctx = Depends(get_ctx)) -> list[MemberOut]:
    ctx.require("member:read")
    return await service.list_members(ctx)


@router.post(
    "/invitations", response_model=InvitationOut, status_code=status.HTTP_201_CREATED
)
async def create_invitation(
    body: InvitationCreate, ctx: Ctx = Depends(get_ctx)
) -> InvitationOut:
    ctx.require("member:write")
    return await service.create_invitation(ctx, body)


@router.get("/invitations", response_model=list[InvitationOut])
async def list_invitations(ctx: Ctx = Depends(get_ctx)) -> list[InvitationOut]:
    ctx.require("member:read")
    return await service.list_invitations(ctx)


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(invitation_id: UUID, ctx: Ctx = Depends(get_ctx)) -> None:
    ctx.require("member:write")
    await service.revoke_invitation(ctx, invitation_id)


@router.patch("/members/{user_id}/role", status_code=status.HTTP_204_NO_CONTENT)
async def update_member_role(
    user_id: UUID, body: MemberRoleUpdate, ctx: Ctx = Depends(get_ctx)
) -> None:
    ctx.require("member:write")
    await service.update_member_role(ctx, user_id, body.role)


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(user_id: UUID, ctx: Ctx = Depends(get_ctx)) -> None:
    ctx.require("member:write")
    await service.remove_member(ctx, user_id)
