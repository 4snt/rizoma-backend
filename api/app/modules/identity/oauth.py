"""Abstração de provedor de login externo (OAuth/OIDC).

Hoje só existe Google (ADR-005: OAuth-only, sem senha). Esta camada existe
para que adicionar um segundo provedor — Microsoft, GitHub, um IdP próprio
de outra instituição que rode o Rizoma — seja implementar um adapter novo
e trocar a injeção em `get_oauth_provider()`, sem tocar em
`service.login_with_google` nem no formato do JWT emitido.

O projeto é software livre (GPL-3.0): outro laboratório rodando sua própria
instância pode querer autenticar contra um provedor diferente do Google
sem fazer fork do módulo de identidade inteiro.
"""
from dataclasses import dataclass
from typing import Protocol

import httpx


@dataclass(frozen=True)
class OAuthClaims:
    """Formato normalizado que todo adapter devolve, independente do
    provedor por trás — `service.py` só conhece isto, nunca o payload cru
    de um provedor específico."""

    sub: str
    email: str
    name: str
    avatar_url: str | None
    email_verified: bool


class OAuthProvider(Protocol):
    """Contrato que qualquer provedor de login externo precisa cumprir."""

    async def verify(self, access_token: str) -> OAuthClaims:
        """Valida o access_token junto ao provedor e devolve as claims
        normalizadas. Levanta ValueError se o token for inválido, expirado,
        ou o e-mail não for verificado."""
        ...


class GoogleOAuthProvider:
    """Adapter para Google OAuth via userinfo endpoint (ADR-005)."""

    USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

    async def verify(self, access_token: str) -> OAuthClaims:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                self.USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if response.status_code != 200:
            raise ValueError(
                f"Google userinfo retornou status {response.status_code}: {response.text}"
            )

        claims: dict = response.json()
        if "error" in claims:
            raise ValueError(f"Google userinfo erro: {claims['error']}")

        if not claims.get("email_verified", False):
            raise ValueError("Email do Google não verificado.")

        email = (claims.get("email") or "").strip().lower()
        return OAuthClaims(
            sub=claims.get("sub", ""),
            email=email,
            name=claims.get("name") or email.split("@")[0],
            avatar_url=claims.get("picture"),
            email_verified=True,
        )


def get_oauth_provider() -> OAuthProvider:
    """Ponto único de injeção. Trocar o provedor default aqui — ou, quando
    existir mais de um, decidir por parâmetro de rota/config em vez de
    retornar sempre GoogleOAuthProvider()."""
    return GoogleOAuthProvider()
