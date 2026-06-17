"""Fixtures de integração.

- `client`: cliente httpx sobre o app ASGI (sem subir servidor). Não dispara o
  lifespan, então só endpoints que não tocam o banco respondem; os demais devem
  ser marcados com a fixture `db_pool`.
- `db_pool`: inicializa o pool asyncpg de verdade e faz `pytest.skip` se o banco
  não estiver acessível — isola os testes que exigem Postgres.
"""
import os

import httpx
import pytest
import pytest_asyncio

from app.main import app


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_pool():
    """Sobe o pool real; pula o teste se o Postgres não estiver disponível."""
    from app.core.database import init_db_pool, close_db_pool, get_pool

    try:
        await init_db_pool()
    except Exception as exc:  # noqa: BLE001 — qualquer falha de conexão = skip
        pytest.skip(f"Postgres indisponível para teste de integração: {exc}")
    try:
        yield get_pool()
    finally:
        await close_db_pool()
