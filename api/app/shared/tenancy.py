"""Isolamento multi-organização via Row-Level Security.

Duas camadas de defesa:
  1. A aplicação decide quem pode o quê (papéis).
  2. O BANCO garante o isolamento. Se um WHERE for esquecido no código, a RLS
     impede que dados de uma organização vazem para outra.

Armadilha 1 (ADR-007) — pool de conexões.
    `SET rizoma.current_org` sem LOCAL grava o GUC na conexão. Ela volta para o
    pool e a próxima requisição — possivelmente de OUTRA organização — herda o
    valor. Vazamento silencioso. Por isso tudo aqui usa
    `set_config(..., is_local => true)`, que morre no COMMIT/ROLLBACK.

Armadilha 2 — "bypass" por GUC.
    A tentação é criar um `rizoma.bypass_rls` para o trabalho de sistema. NÃO
    FAÇA: GUC customizado pode ser setado por qualquer usuário, então uma única
    linha de SQL injetada (`SET rizoma.bypass_rls='on'`) anularia o isolamento
    inteiro. Cross-org exige o PAPEL rizoma_system (BYPASSRLS), que é atributo
    do banco e não se auto-concede.

Armadilha 3 — superusuário.
    Superusuário ignora RLS mesmo com FORCE. O papel de runtime (rizoma_app) é
    NOSUPERUSER NOBYPASSRLS de propósito.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ORG_GUC = "rizoma.current_org"
USER_GUC = "rizoma.current_user"


async def bind_tenant(
    session: AsyncSession, org_id: UUID, user_id: UUID | None = None
) -> None:
    """Amarra a transação corrente a uma organização.

    Precisa rodar DENTRO de uma transação aberta — fora dela, `is_local => true`
    não tem escopo e o valor se perde.
    """
    await session.execute(
        text("SELECT set_config(:k, :v, true)"), {"k": ORG_GUC, "v": str(org_id)}
    )
    if user_id is not None:
        await session.execute(
            text("SELECT set_config(:k, :v, true)"), {"k": USER_GUC, "v": str(user_id)}
        )


async def bind_user(session: AsyncSession, user_id: UUID) -> None:
    """Amarra só o usuário, sem organização.

    É o estado do login: o usuário está autenticado mas ainda não escolheu a org.
    A policy `own_memberships` usa isto para deixá-lo descobrir a que orgs pertence.
    """
    await session.execute(
        text("SELECT set_config(:k, :v, true)"), {"k": USER_GUC, "v": str(user_id)}
    )


@asynccontextmanager
async def tenant_session(
    session: AsyncSession, org_id: UUID, user_id: UUID | None = None
) -> AsyncIterator[AsyncSession]:
    """Transação já amarrada à organização.

        async with tenant_session(session, ctx.org_id, ctx.user_id) as s:
            ...  # tudo aqui enxerga somente a org
    """
    async with session.begin():
        await bind_tenant(session, org_id, user_id)
        yield session
