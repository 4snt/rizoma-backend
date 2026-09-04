"""Testes do LIMS: clientes, projetos, amostras, custódia, idempotência e RLS.

Banco real. Sobe um FastAPI local só com o router do LIMS — não usa app/main.py,
para não depender do que os outros módulos estão fazendo em paralelo.
"""
import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.core.config import settings
from app.core.security import create_access_token
from app.modules.lims.custody import TRANSICOES
from app.modules.lims.router import router as lims_router
from app.shared.ids import new_id
from tests.mvp.conftest import make_member, make_org, make_user, rand_slug

PREFIX = "/api/v2/lims"


@pytest_asyncio.fixture(autouse=True)
async def purge_custody(db):
    """Limpa custody_events antes da limpeza genérica do conftest.

    O conftest apaga as organizações, e o ON DELETE CASCADE tentaria apagar os
    eventos de custódia junto — mas o trigger append-only RECUSA DELETE, e o
    teardown inteiro morre. TRUNCATE não passa por triggers de linha; exige o
    dono da tabela (api_user), daí a conexão própria.

    Depende de `db` de propósito: assim é criado DEPOIS dele e finalizado ANTES,
    que é exatamente a janela necessária.
    """
    yield
    conn = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database=settings.postgres_db,
    )
    try:
        await conn.execute("TRUNCATE custody_events")
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def client():
    app = FastAPI()
    app.include_router(lims_router, prefix=PREFIX)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def auth(user_id, role: str = "org_admin") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id), role)}"}


@pytest_asyncio.fixture
async def org_admin(db):
    """Uma organização com um org_admin dentro. O cenário base de quase tudo."""
    org_id = await make_org(db, slug=rand_slug())
    user_id = await make_user(db)
    await make_member(db, org_id, user_id, "org_admin")
    return org_id, user_id


async def _make_project(client, headers) -> str:
    r = await client.post(
        f"{PREFIX}/projects",
        json={"code": f"P-{new_id().hex[:6]}", "name": "Pós-Fogo"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _make_sample(client, headers, project_id, code="S-01", **extra) -> dict:
    body = {"code": code, "matrix": "solo", **extra}
    r = await client.post(
        f"{PREFIX}/projects/{project_id}/samples", json=body, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


# ── Fluxo feliz: pesquisador → projeto → amostra ────────────────────────
async def test_customer_project_sample_e_listagem(client, org_admin, db):
    org_id, user_id = org_admin
    h = auth(user_id)

    # "Pesquisador" agora é sempre um membro real da organização — não um
    # contato solto criado pelo LIMS.
    pesquisador_id = await make_user(db, name="Embrapa")
    await make_member(db, org_id, pesquisador_id, "bioinformatician")

    r = await client.post(
        f"{PREFIX}/projects",
        json={
            "code": "INOVAHERB",
            "name": "INOVAHERB ITS",
            "customer_user_id": str(pesquisador_id),
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    project = r.json()
    assert project["status"] == "draft"
    assert project["customer_user_id"] == str(pesquisador_id)

    sample = await _make_sample(
        client, h, project["id"], code="INV-001",
        treatment_group="controle", replicate=1, lat=-18.23, lon=-43.6,
        occurred_at="2026-07-01T09:00:00+00:00",
    )
    assert sample["status"] == "planned"
    assert sample["lat"] == pytest.approx(-18.23)
    assert sample["lon"] == pytest.approx(-43.6)
    # occurred_at (coleta, 9h no campo) != recorded_at (chegada ao servidor).
    assert sample["occurred_at"].startswith("2026-07-01T09:00")
    assert sample["recorded_at"] != sample["occurred_at"]

    r = await client.get(f"{PREFIX}/projects", headers=h)
    assert [p["id"] for p in r.json()] == [project["id"]]

    r = await client.get(f"{PREFIX}/projects/{project['id']}/samples", headers=h)
    assert [s["id"] for s in r.json()] == [sample["id"]]

    r = await client.get(f"{PREFIX}/samples/{sample['id']}", headers=h)
    assert r.status_code == 200
    assert r.json()["code"] == "INV-001"


async def test_patch_status_do_projeto(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)

    r = await client.patch(
        f"{PREFIX}/projects/{project_id}/status", json={"status": "approved"}, headers=h
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


# ── Máquina de estados + custódia ───────────────────────────────────────
async def test_transicao_valida_gera_custody_event_seq_1(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)

    r = await client.post(
        f"{PREFIX}/samples/{sample['id']}/transition",
        json={"to_status": "collected", "lat": -18.2, "lon": -43.6},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "collected"

    r = await client.get(f"{PREFIX}/samples/{sample['id']}/custody", headers=h)
    chain = r.json()
    assert len(chain["events"]) == 1
    ev = chain["events"][0]
    assert ev["seq"] == 1
    assert ev["event_type"] == "coleta"
    assert ev["prev_hash"] is None
    assert len(ev["hash"]) == 64
    assert chain["chain_valid"] is True


async def test_transicao_invalida_da_409(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)

    r = await client.post(
        f"{PREFIX}/samples/{sample['id']}/transition",
        json={"to_status": "analyzed"},
        headers=h,
    )
    assert r.status_code == 409, r.text
    assert "planned" in r.json()["detail"]

    # E o estado não se moveu.
    r = await client.get(f"{PREFIX}/samples/{sample['id']}", headers=h)
    assert r.json()["status"] == "planned"


async def test_cadeia_de_custodia_com_3_transicoes(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)

    for target in ("collected", "in_transit", "received"):
        r = await client.post(
            f"{PREFIX}/samples/{sample['id']}/transition",
            json={"to_status": target},
            headers=h,
        )
        assert r.status_code == 200, r.text

    r = await client.get(f"{PREFIX}/samples/{sample['id']}/custody", headers=h)
    chain = r.json()
    assert chain["chain_valid"] is True
    assert [e["seq"] for e in chain["events"]] == [1, 2, 3]
    assert [e["event_type"] for e in chain["events"]] == [
        "coleta", "transporte", "recebimento",
    ]
    # Cada elo aponta para o hash do anterior.
    assert chain["events"][0]["prev_hash"] is None
    assert chain["events"][1]["prev_hash"] == chain["events"][0]["hash"]
    assert chain["events"][2]["prev_hash"] == chain["events"][1]["hash"]


async def test_custody_events_sao_append_only_no_banco(client, org_admin, db):
    """A garantia final não é o código Python — é o trigger do banco."""
    from sqlalchemy import text

    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)
    await client.post(
        f"{PREFIX}/samples/{sample['id']}/transition",
        json={"to_status": "collected"},
        headers=h,
    )

    with pytest.raises(Exception):
        async with db() as s:
            async with s.begin():
                await s.execute(
                    text("UPDATE custody_events SET notes = 'adulterado' WHERE sample_id = :s"),
                    {"s": sample["id"]},
                )


def test_maquina_de_estados_nao_tem_estado_fora_do_check():
    validos = {
        "planned", "collected", "in_transit", "received", "accepted",
        "rejected", "processing", "analyzed", "stored", "consumed", "disposed",
    }
    assert set(TRANSICOES) == validos
    for origem, destinos in TRANSICOES.items():
        assert set(destinos) <= validos, origem
    assert TRANSICOES["consumed"] == []
    assert TRANSICOES["disposed"] == []


# ── Idempotência (tablet offline) ───────────────────────────────────────
async def test_idempotencia_post_amostra_duas_vezes(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)

    sample_id = str(new_id())  # o tablet gera o UUIDv7 offline
    body = {"id": sample_id, "code": "OFF-001", "matrix": "raiz"}
    headers = {**h, "Idempotency-Key": "tablet-42-abc"}

    r1 = await client.post(
        f"{PREFIX}/projects/{project_id}/samples", json=body, headers=headers
    )
    assert r1.status_code == 201, r1.text
    assert r1.json()["id"] == sample_id  # o servidor respeitou o id do tablet

    # A rede caiu; o tablet reenvia. Mesma chave → mesma resposta, sem duplicar.
    r2 = await client.post(
        f"{PREFIX}/projects/{project_id}/samples", json=body, headers=headers
    )
    assert r2.status_code == 201, r2.text
    assert r2.json() == r1.json()

    r = await client.get(f"{PREFIX}/projects/{project_id}/samples", headers=h)
    assert len(r.json()) == 1


# ── Isolamento entre organizações (RLS) ─────────────────────────────────
async def test_org_a_nao_enxerga_projeto_da_org_b(client, db):
    org_a = await make_org(db, slug=rand_slug())
    user_a = await make_user(db)
    await make_member(db, org_a, user_a, "org_admin")

    org_b = await make_org(db, slug=rand_slug())
    user_b = await make_user(db)
    await make_member(db, org_b, user_b, "org_admin")

    ha, hb = auth(user_a), auth(user_b)
    project_b = await _make_project(client, hb)

    # A lista de A não traz nada de B...
    r = await client.get(f"{PREFIX}/projects", headers=ha)
    assert r.status_code == 200
    assert project_b not in [p["id"] for p in r.json()]

    # ...e o acesso direto pelo id também não vaza (RLS, não WHERE no código).
    r = await client.get(f"{PREFIX}/projects/{project_b}", headers=ha)
    assert r.status_code == 404

    # B continua enxergando o que é dele.
    r = await client.get(f"{PREFIX}/projects/{project_b}", headers=hb)
    assert r.status_code == 200


async def test_papel_sem_permissao_de_escrita_recebe_403(client, db):
    org_id = await make_org(db, slug=rand_slug())
    user_id = await make_user(db)
    await make_member(db, org_id, user_id, "viewer")

    r = await client.post(
        f"{PREFIX}/projects",
        json={"code": "X", "name": "X"},
        headers=auth(user_id, "viewer"),
    )
    assert r.status_code == 403
