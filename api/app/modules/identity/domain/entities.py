"""Entidades do domínio de identidade: Usuário, Organização, Convite.

`OrganizationMembership` não é uma tabela — é a organização na perspectiva de
um usuário (organização + papel dele nela), o mesmo dado que
`schemas.OrganizationOut` expõe.
"""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.identity.domain.exceptions import DomainNotAllowedError


def assert_email_domain_allowed(email: str, allowed_domain: str | None) -> None:
    """Política institucional: só e-mails do domínio configurado entram —
    não é invariante de uma entidade específica, é regra do sistema todo."""
    if allowed_domain and not email.endswith(allowed_domain.lower()):
        raise DomainNotAllowedError(
            f"DomainNotAllowed: acesso restrito a e-mails do domínio {allowed_domain}."
        )


@dataclass
class User:
    id: UUID
    email: str
    name: str
    avatar_url: str | None = None
    is_active: bool = True
    last_login: datetime | None = None
    google_sub: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "avatar_url": self.avatar_url,
            "is_active": self.is_active,
            "last_login": self.last_login,
        }


@dataclass
class Organization:
    id: UUID
    slug: str
    name: str
    cnpj: str | None = None
    is_active: bool = True
    role_labels: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.role_labels is None:
            self.role_labels = {}


@dataclass
class OrganizationMembership:
    """A organização como o usuário a enxerga: ela + o papel dele nela."""

    id: UUID
    slug: str
    name: str
    role: str
    role_labels: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.role_labels is None:
            self.role_labels = {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "role": self.role,
            "role_labels": self.role_labels,
        }


@dataclass
class Invitation:
    id: UUID
    organization_id: UUID
    email: str
    role: str
    invited_by: UUID | None = None
    invited_at: datetime | None = None
    accepted_at: datetime | None = None

    @property
    def is_pending(self) -> bool:
        return self.accepted_at is None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "email": self.email,
            "role": self.role,
            "invited_by": self.invited_by,
            "invited_at": self.invited_at,
            "accepted_at": self.accepted_at,
        }
