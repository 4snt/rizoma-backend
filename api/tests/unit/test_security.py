"""Testes unitários de JWT — criação, validação, adulteração e expiração."""
import time

import pytest
from jose import JWTError

from app.core import security
from app.core.security import create_access_token, decode_token


def test_round_trip_claims():
    token = create_access_token(sub="user-123", role="admin")
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["role"] == "admin"
    assert "exp" in payload and "iat" in payload


def test_tampered_token_raises():
    token = create_access_token(sub="user-123", role="researcher")
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    with pytest.raises(JWTError):
        decode_token(tampered)


def test_wrong_secret_raises(monkeypatch):
    token = create_access_token(sub="u", role="researcher")
    monkeypatch.setattr(security.settings, "jwt_secret", "outro-segredo-diferente")
    with pytest.raises(JWTError):
        decode_token(token)


def test_expired_token_raises(monkeypatch):
    # Expira imediatamente (validade negativa)
    monkeypatch.setattr(security.settings, "jwt_access_minutes", -1)
    token = create_access_token(sub="u", role="researcher")
    time.sleep(0.05)
    with pytest.raises(JWTError):
        decode_token(token)
