"""Contexto da requisição: quem é o usuário, em que organização, com que papel.

É o `autorizar()` do §8.3 do plano v2, em código. Duas camadas:
  1. Aqui a aplicação decide (papéis).
  2. A RLS garante no banco (tenancy.py).

Se a camada 1 tiver um bug, a 2 ainda segura. Só a 1 não basta.
"""
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.shared.db import get_sessionmaker
from app.shared.tenancy import bind_tenant, bind_user

_bearer = HTTPBearer()

# Papel → o que pode fazer. Enxuto de propósito: são os papéis que a Fatia 1
# realmente exerce. Os outros do §12.2 entram quando alguém os usar.
PERMISSIONS: dict[str, set[str]] = {
    "org_admin": {
        "customer:read", "customer:write", "project:read", "project:write",
        "sample:read", "sample:write", "file:read", "file:write",
        "job:read", "job:write", "result:read", "result:write", "result:review",
        "report:read", "report:write", "report:sign", "member:read", "member:write",
        "reagent:read", "reagent:write", "equipment:read", "equipment:write",
    },
    "coordinator": {
        "customer:read", "customer:write", "project:read", "project:write",
        "sample:read", "sample:write", "file:read", "file:write",
        "job:read", "job:write", "result:read", "report:read", "report:write",
        "member:read",
        "reagent:read", "reagent:write", "equipment:read", "equipment:write",
    },
    "tech_responsible": {
        "project:read", "sample:read", "file:read", "job:read",
        "result:read", "result:write", "result:review",
        "report:read", "report:write", "report:sign",
        "reagent:read", "equipment:read", "equipment:write",
    },
    "field_tech": {
        "project:read", "sample:read", "sample:write", "file:write", "file:read",
    },
    "lab_tech": {
        "project:read", "sample:read", "sample:write",
        "result:read", "result:write", "file:read", "file:write",
        "reagent:read", "reagent:write", "equipment:read",
    },
    "bioinformatician": {
        "project:read", "sample:read", "file:read", "file:write",
        "job:read", "job:write", "result:read",
    },
    "client": {"project:read", "report:read"},
    "viewer": {"project:read", "sample:read", "result:read", "report:read"},
}


@dataclass(frozen=True)
class Ctx:
    user_id: UUID
    org_id: UUID
    role: str
    session: AsyncSession

    def can(self, permission: str) -> bool:
        return permission in PERMISSIONS.get(self.role, set())

    def require(self, permission: str) -> None:
        if not self.can(permission):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Papel '{self.role}' não tem permissão '{permission}'.",
            )


async def get_session() -> AsyncSession:
    async with get_sessionmaker()() as s:
        yield s


async def get_ctx(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    x_organization: str | None = Header(default=None, alias="X-Organization"),
    session: AsyncSession = Depends(get_session),
) -> Ctx:
    """Valida o JWT, resolve a organização e AMARRA a sessão a ela.

    A transação fica aberta com o GUC de tenant já setado — todo SELECT/INSERT
    do handler já nasce isolado. O commit acontece no fim do handler.
    """
    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido ou expirado.")

    raw_user = payload.get("sub")
    if not raw_user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token malformado.")
    user_id = UUID(raw_user)

    # O membership decide a org e o papel — nunca o cliente. Um X-Organization
    # apontando para uma org da qual o usuário não é membro tem que dar 403.
    await session.begin()
    await bind_user(session, user_id)

    if x_organization:
        try:
            org_id = UUID(x_organization)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Organization inválido.")
        row = (
            await session.execute(
                text(
                    "SELECT organization_id, role FROM organization_members "
                    "WHERE user_id = :u AND organization_id = :o"
                ),
                {"u": str(user_id), "o": str(org_id)},
            )
        ).first()
    else:
        row = (
            await session.execute(
                text(
                    "SELECT organization_id, role FROM organization_members "
                    "WHERE user_id = :u ORDER BY created_at LIMIT 1"
                ),
                {"u": str(user_id)},
            )
        ).first()

    if row is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Usuário não é membro desta organização.",
        )

    org_id, role = row[0], row[1]
    await bind_tenant(session, org_id, user_id)

    try:
        yield Ctx(user_id=user_id, org_id=org_id, role=role, session=session)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
