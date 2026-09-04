"""Testes dos dados biológicos da amostra: organism_type, morfologia de
colônia, testes bioquímicos/enzimáticos (catálogo aberto) e genes
sequenciados.

Banco real. Reaproveita fixtures/helpers de `test_lims.py`.
"""
import httpx
import pytest_asyncio
from fastapi import FastAPI

from app.core.security import create_access_token
from app.modules.lims.router import router as lims_router
from tests.mvp.conftest import make_member, make_org, make_user, rand_slug

PREFIX = "/api/v2/lims"


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
    org_id = await make_org(db, slug=rand_slug())
    user_id = await make_user(db)
    await make_member(db, org_id, user_id, "org_admin")
    return org_id, user_id


async def _make_project(client, headers) -> str:
    from app.shared.ids import new_id

    r = await client.post(
        f"{PREFIX}/projects",
        json={"code": f"P-{new_id().hex[:6]}", "name": "Isolados"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _make_sample(client, headers, project_id, code="BAC-01", **extra) -> dict:
    body = {"code": code, "matrix": "cultura_microbiana", **extra}
    r = await client.post(
        f"{PREFIX}/projects/{project_id}/samples", json=body, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


# ── Morfologia ──────────────────────────────────────────────────────────
async def test_criar_amostra_com_organism_type_e_morfologia_completa(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)

    sample = await _make_sample(
        client, h, project_id,
        organism_type="bacteria",
        colonia_forma="circular",
        colonia_elevacao="convexa",
        colonia_margem="inteira",
        colonia_cor="branco-amarelada",
        colonia_textura="mucoide",
        colonia_tamanho_mm=2.5,
        colonia_opacidade="opaca",
    )
    assert sample["organism_type"] == "bacteria"
    assert sample["colonia_forma"] == "circular"
    assert sample["colonia_tamanho_mm"] == 2.5

    r = await client.get(f"{PREFIX}/samples/{sample['id']}", headers=h)
    assert r.json()["colonia_opacidade"] == "opaca"


async def test_patch_morphology_parcial_nao_apaga_outros_campos(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(
        client, h, project_id,
        organism_type="bacteria", colonia_forma="circular", colonia_cor="branca",
    )

    r = await client.patch(
        f"{PREFIX}/samples/{sample['id']}/morphology",
        json={"colonia_cor": "amarela"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["colonia_cor"] == "amarela"
    assert updated["colonia_forma"] == "circular"  # não foi tocado
    assert updated["organism_type"] == "bacteria"


async def test_morfologia_com_valor_fora_do_vocabulario_da_422(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)

    r = await client.patch(
        f"{PREFIX}/samples/{sample['id']}/morphology",
        json={"colonia_forma": "quadrada"},
        headers=h,
    )
    assert r.status_code == 422


# ── Testes bioquímicos/enzimáticos (catálogo aberto) ───────────────────
async def test_criar_teste_com_nome_fora_de_qualquer_lista_fixa(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)

    r = await client.post(
        f"{PREFIX}/samples/{sample['id']}/tests",
        json={"test_name": "Um Teste Bem Novo Que Ninguém Cadastrou Antes", "result": "+"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["test_name"] == "Um Teste Bem Novo Que Ninguém Cadastrou Antes"
    assert r.json()["result"] == "+"


async def test_listar_testes_em_ordem_de_criacao(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)

    for name in ("Catalase", "Urease", "Oxidase"):
        r = await client.post(
            f"{PREFIX}/samples/{sample['id']}/tests",
            json={"test_name": name, "result": "+"},
            headers=h,
        )
        assert r.status_code == 201, r.text

    r = await client.get(f"{PREFIX}/samples/{sample['id']}/tests", headers=h)
    assert r.status_code == 200
    assert [t["test_name"] for t in r.json()] == ["Catalase", "Urease", "Oxidase"]


# ── Genes sequenciados ──────────────────────────────────────────────────
async def test_criar_gene_com_purpose_invalido_da_422(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)

    r = await client.post(
        f"{PREFIX}/samples/{sample['id']}/genes",
        json={"gene": "16S", "purpose": "curar_cancer"},
        headers=h,
    )
    assert r.status_code == 422


async def test_criar_gene_sem_ncbi_accession_e_aceito(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)

    r = await client.post(
        f"{PREFIX}/samples/{sample['id']}/genes",
        json={"gene": "16S", "purpose": "identificacao", "result": "Bacillus subtilis"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ncbi_accession"] is None
    assert body["result"] == "Bacillus subtilis"

    r = await client.get(f"{PREFIX}/samples/{sample['id']}/genes", headers=h)
    assert len(r.json()) == 1


# ── RLS + permissão ──────────────────────────────────────────────────────
async def test_teste_de_amostra_de_outra_org_nao_vaza(client, db):
    org_a = await make_org(db, slug=rand_slug())
    user_a = await make_user(db)
    await make_member(db, org_a, user_a, "org_admin")

    org_b = await make_org(db, slug=rand_slug())
    user_b = await make_user(db)
    await make_member(db, org_b, user_b, "org_admin")

    ha, hb = auth(user_a), auth(user_b)
    project_b = await _make_project(client, hb)
    sample_b = await _make_sample(client, hb, project_b)

    r = await client.post(
        f"{PREFIX}/samples/{sample_b['id']}/tests",
        json={"test_name": "Catalase", "result": "+"},
        headers=hb,
    )
    assert r.status_code == 201, r.text

    # A org A não enxerga a amostra de B — nem pra ler seus testes.
    r = await client.get(f"{PREFIX}/samples/{sample_b['id']}/tests", headers=ha)
    assert r.status_code == 404


async def test_papel_sem_sample_write_recebe_403_ao_criar_teste(client, db):
    org_id = await make_org(db, slug=rand_slug())
    admin_id = await make_user(db)
    await make_member(db, org_id, admin_id, "org_admin")
    viewer_id = await make_user(db)
    await make_member(db, org_id, viewer_id, "viewer")

    h_admin = auth(admin_id)
    project_id = await _make_project(client, h_admin)
    sample = await _make_sample(client, h_admin, project_id)

    r = await client.post(
        f"{PREFIX}/samples/{sample['id']}/tests",
        json={"test_name": "Catalase", "result": "+"},
        headers=auth(viewer_id, "viewer"),
    )
    assert r.status_code == 403
