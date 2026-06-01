"""JWT creation and validation utilities."""
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"


def create_access_token(sub: str, role: str) -> str:
    """Create a signed JWT access token.

    Args:
        sub: User UUID as string (subject claim).
        role: User role ('researcher' or 'admin').

    Returns:
        Encoded JWT string.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_minutes)
    payload = {
        "sub": sub,
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token.

    Args:
        token: Raw JWT string.

    Returns:
        Decoded payload dict containing at least 'sub' and 'role'.

    Raises:
        JWTError: If the token is invalid, expired, or tampered.
    """
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
