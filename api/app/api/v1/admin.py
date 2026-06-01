"""Admin-only endpoints: user management and invite management."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.auth_deps import require_admin
from app.core.config import settings
from app.core.database import get_pool

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class InviteRequest(BaseModel):
    email: str
    role: str = "researcher"


class RoleUpdateRequest(BaseModel):
    role: str


# ---------------------------------------------------------------------------
# GET /users
# ---------------------------------------------------------------------------


@router.get("/users")
async def list_users(_admin: dict = Depends(require_admin)):
    """Return all registered users."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, email, name, role, is_active, last_login
            FROM users
            ORDER BY created_at DESC
            """
        )
    return [
        {
            "id": str(r["id"]),
            "email": r["email"],
            "name": r["name"],
            "role": r["role"],
            "is_active": r["is_active"],
            "last_login": r["last_login"].isoformat() if r["last_login"] else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# GET /invites
# ---------------------------------------------------------------------------


@router.get("/invites")
async def list_pending_invites(_admin: dict = Depends(require_admin)):
    """Return all invites that have not been used yet."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT i.id, i.email, i.role, i.invited_at, u.email AS invited_by_email
            FROM invited_users i
            LEFT JOIN users u ON u.id = i.invited_by
            WHERE i.used_at IS NULL
            ORDER BY i.invited_at DESC
            """
        )
    return [
        {
            "id": str(r["id"]),
            "email": r["email"],
            "role": r["role"],
            "invited_at": r["invited_at"].isoformat(),
            "invited_by_email": r["invited_by_email"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# POST /invites
# ---------------------------------------------------------------------------


@router.post("/invites", status_code=status.HTTP_201_CREATED)
async def create_invite(
    body: InviteRequest,
    admin: dict = Depends(require_admin),
):
    """Create a new invite for an email that is not yet registered."""
    if not body.email.endswith(settings.allowed_email_domain):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Apenas emails {settings.allowed_email_domain} podem ser convidados.",
        )

    if body.role not in ("researcher", "admin"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Role inválida. Use 'researcher' ou 'admin'.",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        # Prevent duplicate invites for already-registered users
        already_registered = await conn.fetchval(
            "SELECT 1 FROM users WHERE email = $1", body.email
        )
        if already_registered:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este email já está registrado na plataforma.",
            )

        try:
            row = await conn.fetchrow(
                """
                INSERT INTO invited_users (email, role, invited_by)
                VALUES ($1, $2, $3)
                ON CONFLICT (email) DO UPDATE
                    SET role       = EXCLUDED.role,
                        invited_by = EXCLUDED.invited_by,
                        invited_at = NOW(),
                        used_at    = NULL
                RETURNING id, email, role, invited_at
                """,
                body.email,
                body.role,
                uuid.UUID(admin["user_id"]),
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Erro ao criar convite: {exc}",
            )

    return {
        "id": str(row["id"]),
        "email": row["email"],
        "role": row["role"],
        "invited_at": row["invited_at"].isoformat(),
    }


# ---------------------------------------------------------------------------
# DELETE /invites/{invite_id}
# ---------------------------------------------------------------------------


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invite(
    invite_id: str,
    _admin: dict = Depends(require_admin),
):
    """Delete a pending (unused) invite."""
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM invited_users
            WHERE id = $1
              AND used_at IS NULL
            """,
            uuid.UUID(invite_id),
        )
    # asyncpg returns 'DELETE N' — check count
    deleted = int(result.split()[-1])
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Convite não encontrado ou já utilizado.",
        )


# ---------------------------------------------------------------------------
# PATCH /users/{user_id}/role
# ---------------------------------------------------------------------------


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    body: RoleUpdateRequest,
    _admin: dict = Depends(require_admin),
):
    """Change the role of a user."""
    if body.role not in ("researcher", "admin"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Role inválida. Use 'researcher' ou 'admin'.",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            """
            UPDATE users
            SET role = $1
            WHERE id = $2
            RETURNING id, email, role
            """,
            body.role,
            uuid.UUID(user_id),
        )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado.",
        )

    return {"id": str(user["id"]), "email": user["email"], "role": user["role"]}


# ---------------------------------------------------------------------------
# PATCH /users/{user_id}/deactivate
# ---------------------------------------------------------------------------


@router.patch("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: str,
    _admin: dict = Depends(require_admin),
):
    """Deactivate a user account (soft-delete)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            """
            UPDATE users
            SET is_active = FALSE
            WHERE id = $1
            RETURNING id, email, is_active
            """,
            uuid.UUID(user_id),
        )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado.",
        )

    return {"id": str(user["id"]), "email": user["email"], "is_active": user["is_active"]}


# ---------------------------------------------------------------------------
# PATCH /users/{user_id}/activate
# ---------------------------------------------------------------------------


@router.patch("/users/{user_id}/activate")
async def activate_user(
    user_id: str,
    _admin: dict = Depends(require_admin),
):
    """Re-activate a previously deactivated user account."""
    pool = get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            """
            UPDATE users
            SET is_active = TRUE
            WHERE id = $1
            RETURNING id, email, is_active
            """,
            uuid.UUID(user_id),
        )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado.",
        )

    return {"id": str(user["id"]), "email": user["email"], "is_active": user["is_active"]}
