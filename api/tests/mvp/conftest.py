"""Fixtures dos testes do MVP.

Os testes batem no Postgres de verdade — RLS não se testa com mock. O papel
`rizoma_system` (BYPASSRLS) monta e limpa os dados; o app roda com `rizoma_app`,
que é justamente quem sofre a RLS.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.identity import service
from app.modules.identity.router import router as identity_router
from app.shared.db import dispose_engine
from app.shared.ids import new_id

PREFIX = "/api/v2/identity"

# Marcadores dos dados de teste — a limpeza se apoia neles.
#
# O RUN_ID não é enfeite: o Postgres é UM só e há mais de uma suíte rodando
# contra ele. Uma limpeza que apagasse `ztest-%` inteiro derrubaria as linhas
# que OUTRO processo de teste está usando naquele instante — e o sintoma
# aparece como um 403 aleatório num teste que não tem nada de errado. Cada
# processo só apaga o que ele mesmo criou.
BASE_PREFIX = "ztest-"
RUN_ID = uuid.uuid4().hex[:6]
SLUG_PREFIX = f"{BASE_PREFIX}{RUN_ID}-"
EMAIL_PREFIX = f"{BASE_PREFIX}{RUN_ID}-"


def unique(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def rand_email() -> str:
    return f"{EMAIL_PREFIX}{uuid.uuid4().hex[:10]}@ufvjm.edu.br"


def rand_slug() -> str:
    return f"{SLUG_PREFIX}{uuid.uuid4().hex[:10]}"


# Nomes antigos. Preferir rand_*: um helper chamado `test_*` que outro módulo
# importa vira "teste" aos olhos do pytest e infla a contagem com nada.
# `__test__ = False` impede a coleta enquanto os aliases existirem.
test_email = rand_email
test_slug = rand_slug
for _f in (rand_email, rand_slug):
    _f.__test__ = False


@pytest_asyncio.fixture
async def sys_engine():
    """Engine com BYPASSRLS para preparar e limpar o cenário."""
    engine = create_async_engine(service._system_dsn(), poolclass=None)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f"Postgres indisponível: {exc}")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(sys_engine):
    """Sessionmaker de sistema + limpeza dos dados marcados ao fim do teste."""
    maker = async_sessionmaker(sys_engine, expire_on_commit=False)
    yield maker
    async with maker() as s:
        async with s.begin():
            # Só o que ESTE processo criou. ON DELETE CASCADE leva members e
            # invitations junto.
            await s.execute(
                text("DELETE FROM organizations WHERE slug LIKE :p"),
                {"p": f"{SLUG_PREFIX}%"},
            )
            await s.execute(
                text("DELETE FROM users WHERE email LIKE :p"),
                {"p": f"{EMAIL_PREFIX}%"},
            )
            # Sobras de runs que morreram no meio. A idade evita encostar em
            # qualquer processo vivo.
            await s.execute(
                text(
                    "DELETE FROM organizations WHERE slug LIKE :p "
                    "AND created_at < now() - interval '1 hour'"
                ),
                {"p": f"{BASE_PREFIX}%"},
            )
            await s.execute(
                text(
                    "DELETE FROM users WHERE email LIKE :p "
                    "AND created_at < now() - interval '1 hour'"
                ),
                {"p": f"{BASE_PREFIX}%"},
            )
    # Os engines globais guardam conexões presas ao event loop deste teste; o
    # próximo teste roda em outro loop. Sem descartar, asyncpg estoura.
    await dispose_engine()
    await service.dispose_system_engine()


@pytest_asyncio.fixture
async def client():
    app = FastAPI()
    app.include_router(identity_router, prefix=PREFIX)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Helpers de cenário ──────────────────────────────────────────────────────


async def make_user(maker, email: str | None = None, name: str = "Teste") -> uuid.UUID:
    user_id = new_id()
    async with maker() as s:
        async with s.begin():
            await s.execute(
                text("INSERT INTO users (id, email, name) VALUES (:i, :e, :n)"),
                {"i": str(user_id), "e": email or rand_email(), "n": name},
            )
    return user_id


async def make_org(maker, slug: str | None = None, name: str = "Org Teste") -> uuid.UUID:
    org_id = new_id()
    async with maker() as s:
        async with s.begin():
            await s.execute(
                text("INSERT INTO organizations (id, slug, name) VALUES (:i, :s, :n)"),
                {"i": str(org_id), "s": slug or rand_slug(), "n": name},
            )
    return org_id


async def make_member(maker, org_id, user_id, role: str = "org_admin") -> None:
    async with maker() as s:
        async with s.begin():
            await s.execute(
                text(
                    "INSERT INTO organization_members (id, organization_id, user_id, role) "
                    "VALUES (:i, :o, :u, :r)"
                ),
                {"i": str(new_id()), "o": str(org_id), "u": str(user_id), "r": role},
            )


async def make_invitation(maker, org_id, email: str, role: str = "lab_tech") -> uuid.UUID:
    inv_id = new_id()
    async with maker() as s:
        async with s.begin():
            await s.execute(
                text(
                    "INSERT INTO invitations (id, organization_id, email, role) "
                    "VALUES (:i, :o, :e, :r)"
                ),
                {"i": str(inv_id), "o": str(org_id), "e": email, "r": role},
            )
    return inv_id
