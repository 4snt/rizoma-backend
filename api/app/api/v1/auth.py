"""Authentication endpoints: Google OAuth login and current-user info."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.auth_deps import get_current_user
from app.core.config import settings
from app.core.database import get_pool
from app.core.google_auth import verify_google_token
from app.core.security import create_access_token

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class GoogleLoginRequest(BaseModel):
    access_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    role: str
    email: str
    name: str


class MeResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    last_login: str | None


# ---------------------------------------------------------------------------
# POST /google
# ---------------------------------------------------------------------------


@router.post("/google", response_model=TokenResponse)
async def login_with_google(body: GoogleLoginRequest):
    """Exchange a Google id_token for a platform JWT."""
    import logging as _log
    _log.getLogger("uvicorn.error").warning("AUTH ENTER token_len=%d", len(body.access_token))
    # Step 1 — validate with Google
    try:
        claims = await verify_google_token(body.access_token, settings.google_client_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token Google inválido: {exc}",
        )

    email: str = claims.get("email", "")
    name: str = claims.get("name", email.split("@")[0])
    google_sub: str = claims.get("sub", "")

    # Step 2 — domain check
    if not email.endswith(settings.allowed_email_domain):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"[DBG] domain: email={email!r} required={settings.allowed_email_domain!r}",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        # Step 3 — bootstrap check
        user_count: int = await conn.fetchval("SELECT COUNT(*) FROM users")
        is_bootstrap = user_count == 0

        if is_bootstrap:
            role = "admin"
        else:
            # Step 4 — existing user or pending invite
            existing_user = await conn.fetchrow(
                "SELECT role FROM users WHERE email = $1",
                email,
            )
            if existing_user:
                role = existing_user["role"]
            else:
                invite = await conn.fetchrow(
                    """
                    SELECT id, role
                    FROM invited_users
                    WHERE email = $1
                      AND used_at IS NULL
                    """,
                    email,
                )
                if invite is None:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"[DBG] no-invite: email={email!r} existing={existing_user is not None}",
                    )
                role = invite["role"]

        # Step 5 — upsert user
        user = await conn.fetchrow(
            """
            INSERT INTO users (email, name, google_sub, role, last_login)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (email) DO UPDATE
                SET google_sub  = EXCLUDED.google_sub,
                    name        = EXCLUDED.name,
                    last_login  = NOW()
            RETURNING id, email, name, role, is_active
            """,
            email,
            name,
            google_sub,
            role,
        )

        if not user["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"[DBG] inactive: email={email!r}",
            )

        # Step 6 — mark invite as used (only for new users arriving via invite)
        if not is_bootstrap and not existing_user:
            await conn.execute(
                """
                UPDATE invited_users
                SET used_at = NOW()
                WHERE email = $1
                  AND used_at IS NULL
                """,
                email,
            )

    access_token = create_access_token(sub=str(user["id"]), role=user["role"])

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        role=user["role"],
        email=user["email"],
        name=user["name"],
    )


# ---------------------------------------------------------------------------
# GET /me
# ---------------------------------------------------------------------------


@router.get("/me", response_model=MeResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Return the authenticated user's profile from the database."""
    pool = get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            """
            SELECT id, email, name, role, last_login
            FROM users
            WHERE id = $1
              AND is_active = TRUE
            """,
            current_user["user_id"],
        )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado ou desativado.",
        )

    return MeResponse(
        id=str(user["id"]),
        email=user["email"],
        name=user["name"],
        role=user["role"],
        last_login=user["last_login"].isoformat() if user["last_login"] else None,
    )
