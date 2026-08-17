"""Contratos de entrada/saída do módulo de identidade (Pydantic v2)."""
import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.shared.context import PERMISSIONS

VALID_ROLES: frozenset[str] = frozenset(PERMISSIONS)

# Validação local em vez de `EmailStr`: `pydantic[email]` puxa a lib
# email-validator, e não vale uma dependência nova só para isto.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class GoogleLoginIn(BaseModel):
    access_token: str = Field(min_length=1)


class UserOut(BaseModel):
    id: UUID
    email: str
    name: str
    avatar_url: str | None = None
    is_active: bool = True
    last_login: datetime | None = None


class RoleLabelEntry(BaseModel):
    """Um rótulo customizado agrupando um ou mais papéis técnicos. Um
    laboratório pode chamar `field_tech` + `lab_tech` juntos de "Bolsista",
    por exemplo — por isso `roles` é lista, não um papel único. E o mesmo
    papel técnico pode aparecer em mais de uma entrada (ex.: "Mestrando" e
    "Doutorando" os dois cobrindo `lab_tech`)."""

    label: str = Field(min_length=1, max_length=80)
    roles: list[str] = Field(min_length=1)

    @field_validator("roles")
    @classmethod
    def _known_roles(cls, v: list[str]) -> list[str]:
        unknown = set(v) - VALID_ROLES
        if unknown:
            raise ValueError(
                f"Papéis desconhecidos: {', '.join(sorted(unknown))}. "
                f"Válidos: {', '.join(sorted(VALID_ROLES))}."
            )
        return v


class OrganizationOut(BaseModel):
    """Organização na perspectiva de um usuário — por isso carrega o papel dele."""

    id: UUID
    slug: str
    name: str
    role: str
    # Catálogo de rótulos da org: vários rótulos podem apontar pro mesmo
    # papel técnico (ex.: "Mestrando" e "Doutorando" os dois em lab_tech).
    # Papel sem nenhuma entrada aqui usa o rótulo padrão do frontend.
    role_labels: list[RoleLabelEntry] = Field(default_factory=list)


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    organizations: list[OrganizationOut]


class MeOut(BaseModel):
    user: UserOut
    organization: OrganizationOut | None
    role: str
    organizations: list[OrganizationOut]


class OrganizationCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=200)
    cnpj: str | None = None


class MemberOut(BaseModel):
    id: UUID
    user_id: UUID
    email: str
    name: str
    role: str
    created_at: datetime


class InvitationCreate(BaseModel):
    email: str
    role: str

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("E-mail inválido.")
        return v

    @field_validator("role")
    @classmethod
    def _known_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(
                f"Papel '{v}' desconhecido. Válidos: {', '.join(sorted(VALID_ROLES))}."
            )
        return v


class MemberRoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def _known_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(
                f"Papel '{v}' desconhecido. Válidos: {', '.join(sorted(VALID_ROLES))}."
            )
        return v


class RoleLabelsUpdate(BaseModel):
    """Substitui o catálogo inteiro de rótulos da organização — não é um
    PATCH incremental. Enviar uma lista menor apaga os rótulos ausentes
    (o cliente é quem lê o estado atual e reenvia completo)."""

    role_labels: list[RoleLabelEntry]


class InvitationOut(BaseModel):
    id: UUID
    organization_id: UUID
    email: str
    role: str
    invited_by: UUID | None
    invited_at: datetime
    accepted_at: datetime | None
