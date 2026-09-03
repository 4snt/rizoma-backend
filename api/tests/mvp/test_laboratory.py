"""Resultados de laboratório: append-only, LOD e segregação de funções.

Banco REAL. As garantias testadas aqui (append-only, reviewed_by <> created_by)
moram no Postgres; contra um mock, este arquivo não provaria nada.
"""
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.security import create_access_token
from app.modules.laboratory.router import router as lab_router
from app.shared.ids import new_id

from .conftest import make_member, make_org, make_user, rand_slug

LAB = "/api/v2/lab"


async def purge_lab_data(org_id) -> None:
    """Limpa `result_versions` de um teste — e só um teste consegue fazer isso.

    A tabela é append-only por TRIGGER, então nem o DELETE em cascata de
    `DELETE FROM organizations` (que a limpeza do conftest faz) passa: o Postgres
    recusa e a organização fica impossível de remover.

    `session_replication_role = 'replica'` desliga os triggers de usuário nesta
    conexão. Exige superusuário — é por isso que a aplicação NUNCA conseguiria
    fazer isto: `rizoma_app` é NOSUPERUSER de propósito. A garantia continua de pé
    no caminho real; aqui é a faxina do laboratório, com a chave do dono.
    """
    dsn = (
        f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )
    engine = create_async_engine(dsn, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("SET session_replication_role = 'replica'")
            await conn.execute(
                text("DELETE FROM result_versions WHERE organization_id = :o"),
                {"o": str(org_id)},
            )
            await conn.execute(
                text("DELETE FROM lab_results WHERE organization_id = :o"),
                {"o": str(org_id)},
            )
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client():
    """Sobrescreve o `client` do conftest (que monta o router de identidade)."""
    app = FastAPI()
    app.include_router(lab_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def scenario(db):
    """Organização, projeto, amostra e DOIS usuários.

    Dois usuários não é conveniência: sem um produtor e um revisor distintos, a
    segregação de funções é intestável.

    Ambos são `tech_responsible` — papel que tem result:write E result:review. Se
    o produtor não tivesse permissão de revisar, o 403 da auto-aprovação viria da
    checagem de PAPEL, e a regra que queremos provar (quem produz não aprova)
    passaria despercebida.
    """
    org_id = await make_org(db, slug=rand_slug(), name="Laboratório Rizoma")
    producer = await make_user(db, name="Ana Produtora")
    reviewer = await make_user(db, name="Bruno Revisor")
    await make_member(db, org_id, producer, role="tech_responsible")
    await make_member(db, org_id, reviewer, role="tech_responsible")

    project_id, sample_id = new_id(), new_id()
    async with db() as s:
        async with s.begin():
            await s.execute(
                text(
                    "INSERT INTO projects (id, organization_id, code, name, status) "
                    "VALUES (:i, :o, :c, 'INOVAHERB', 'in_progress')"
                ),
                {"i": str(project_id), "o": str(org_id), "c": f"PRJ-{str(project_id)[:8]}"},
            )
            await s.execute(
                text(
                    "INSERT INTO samples (id, organization_id, project_id, code, matrix, status) "
                    "VALUES (:i, :o, :p, :c, 'solo', 'received')"
                ),
                {"i": str(sample_id), "o": str(org_id), "p": str(project_id),
                 "c": f"AM-{str(sample_id)[:8]}"},
            )

    def headers(user_id):
        return {
            "Authorization": f"Bearer {create_access_token(str(user_id), 'tech_responsible')}",
            "X-Organization": str(org_id),
        }

    yield {
        "org_id": org_id,
        "sample_id": sample_id,
        "project_id": project_id,
        "producer": producer,
        "reviewer": reviewer,
        "producer_h": headers(producer),
        "reviewer_h": headers(reviewer),
    }

    # Roda ANTES da limpeza do conftest (que apaga a organização): sem isto, o
    # cascade esbarra no trigger append-only e a org nunca sai.
    await purge_lab_data(org_id)


async def _create(client, sc, **overrides):
    body = {"analyte": "Cádmio", "method": "ICP-MS", "value_numeric": 1.25, "unit": "mg/kg"}
    body.update(overrides)
    return await client.post(
        f"{LAB}/samples/{sc['sample_id']}/results", json=body, headers=sc["producer_h"]
    )


async def test_cria_resultado_com_unidade(client, scenario):
    r = await _create(client, scenario)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["analyte"] == "Cádmio"
    assert body["current"]["version"] == 1
    assert body["current"]["unit"] == "mg/kg"
    assert body["current"]["status"] == "submitted"
    assert body["current"]["below_lod"] is False
    assert len(body["history"]) == 1


async def test_resultado_sem_unidade_e_recusado(client, scenario):
    """Um número sem unidade não é um resultado (§5.5). O schema barra antes do banco."""
    r = await client.post(
        f"{LAB}/samples/{scenario['sample_id']}/results",
        json={"analyte": "Cádmio", "value_numeric": 1.25},
        headers=scenario["producer_h"],
    )
    assert r.status_code in (400, 422), r.text


async def test_abaixo_do_lod_vira_menor_que(client, scenario):
    """'<0.05' é um resultado válido. Tratá-lo como 0 ou null falsifica o laudo."""
    r = await _create(client, scenario, value_numeric=0.01, lod=0.05, loq=0.15)
    assert r.status_code == 201, r.text
    cur = r.json()["current"]
    assert cur["below_lod"] is True
    assert cur["display_value"] == "<0.05"


async def test_correcao_sem_motivo_e_recusada(client, scenario):
    created = await _create(client, scenario)
    rid = created.json()["id"]

    r = await client.post(
        f"{LAB}/results/{rid}/correct",
        json={"value_numeric": 2.0},
        headers=scenario["producer_h"],
    )
    assert r.status_code == 400, r.text
    assert "change_reason" in r.text


async def test_correcao_cria_versao_nova_e_preserva_a_antiga(client, scenario, db):
    """A prova do append-only: a versão 1 continua no banco, intacta."""
    created = await _create(client, scenario, value_numeric=1.25)
    rid = created.json()["id"]

    r = await client.post(
        f"{LAB}/results/{rid}/correct",
        json={"value_numeric": 2.5, "change_reason": "Erro de diluição na alíquota."},
        headers=scenario["producer_h"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current"]["version"] == 2
    assert body["current"]["change_reason"] == "Erro de diluição na alíquota."
    assert body["current"]["supersedes"] == body["history"][0]["id"]
    assert len(body["history"]) == 2

    # A versão 1 sobreviveu — e com o valor ORIGINAL, não o corrigido.
    async with db() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT version, value_numeric FROM result_versions "
                    "WHERE result_id = :r ORDER BY version"
                ),
                {"r": rid},
            )
        ).fetchall()
    assert [r.version for r in rows] == [1, 2]
    assert float(rows[0].value_numeric) == 1.25
    assert float(rows[1].value_numeric) == 2.5


async def test_update_direto_no_banco_e_recusado(scenario, db, client):
    """O append-only não é uma convenção do código — é o Postgres recusando."""
    created = await _create(client, scenario)
    rid = created.json()["id"]

    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError) as exc:
        async with db() as s:
            async with s.begin():
                await s.execute(
                    text("UPDATE result_versions SET value_numeric = 999 WHERE result_id = :r"),
                    {"r": rid},
                )
    assert "append-only" in str(exc.value)


async def test_auto_aprovacao_e_bloqueada(client, scenario):
    """Segregação de funções: quem produziu o resultado não pode aprová-lo.

    O produtor TEM a permissão result:review. O 403 aqui vem da regra de
    domínio, não do papel.
    """
    created = await _create(client, scenario)
    rid = created.json()["id"]

    r = await client.post(
        f"{LAB}/results/{rid}/review",
        json={"status": "approved"},
        headers=scenario["producer_h"],
    )
    assert r.status_code == 403, r.text
    assert "Segregação" in r.json()["detail"]


async def test_revisao_por_outro_usuario_aprova(client, scenario):
    created = await _create(client, scenario)
    rid = created.json()["id"]

    r = await client.post(
        f"{LAB}/results/{rid}/review",
        json={"status": "approved"},
        headers=scenario["reviewer_h"],
    )
    assert r.status_code == 200, r.text
    cur = r.json()["current"]
    assert cur["version"] == 2
    assert cur["status"] == "approved"
    assert cur["reviewed_by"] == str(scenario["reviewer"])
    # A autoria do RESULTADO continua sendo do produtor — o revisor não vira autor.
    assert cur["created_by"] == str(scenario["producer"])


async def test_lista_resultados_traz_corrente_e_historico(client, scenario):
    created = await _create(client, scenario)
    rid = created.json()["id"]
    await client.post(
        f"{LAB}/results/{rid}/correct",
        json={"value_numeric": 9.9, "change_reason": "Recalibração do equipamento."},
        headers=scenario["producer_h"],
    )

    r = await client.get(
        f"{LAB}/samples/{scenario['sample_id']}/results", headers=scenario["producer_h"]
    )
    assert r.status_code == 200, r.text
    (item,) = r.json()
    assert item["current"]["version"] == 2
    assert len(item["history"]) == 2
