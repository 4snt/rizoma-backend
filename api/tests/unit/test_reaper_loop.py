"""Loop do reaper: uma iteração que falha NÃO pode derrubar a task.

O `reap_orphan_jobs` (a query em si) é exercitado nos testes de jobs contra o
banco. Aqui isolamos o CONTRATO do loop — swallow de exceção + parada limpa no
cancelamento — sem tocar no Postgres.
"""
import asyncio

import pytest

from app.modules.jobs import reaper


@pytest.mark.asyncio
async def test_loop_engole_excecao_de_uma_iteracao_e_segue(monkeypatch):
    calls = {"n": 0}

    async def fake_reap():
        calls["n"] += 1
        raise RuntimeError("banco caiu nesta iteração")

    # O sleep marca o fim da iteração: na 2ª vez, cancela para o loop sair.
    async def fake_sleep(_):
        if calls["n"] >= 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(reaper, "reap_orphan_jobs", fake_reap)
    monkeypatch.setattr(reaper.asyncio, "sleep", fake_sleep)

    # A RuntimeError de cada iteração é engolida; só o CancelledError encerra.
    with pytest.raises(asyncio.CancelledError):
        await reaper.reaper_loop(interval_seconds=0)

    assert calls["n"] >= 2  # rodou mais de uma vez apesar das falhas


@pytest.mark.asyncio
async def test_loop_propaga_cancelamento_imediatamente(monkeypatch):
    async def fake_reap():
        raise asyncio.CancelledError()

    monkeypatch.setattr(reaper, "reap_orphan_jobs", fake_reap)

    with pytest.raises(asyncio.CancelledError):
        await reaper.reaper_loop(interval_seconds=0)
