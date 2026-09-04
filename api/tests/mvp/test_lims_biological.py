"""Testes dos dados biológicos da amostra: organism_type, morfologia de
colônia, registro do isolado (origem/cultivo/microscopia), testes
bioquímicos/enzimáticos (catálogo aberto), genes sequenciados (FASTA +
BLAST) e alíquotas.

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
        f"{PREFIX}/samples/{sample['id']}",
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
        f"{PREFIX}/samples/{sample['id']}",
        json={"colonia_forma": "quadrada"},
        headers=h,
    )
    assert r.status_code == 422


# ── Registro do isolado (PATCH /samples/{id}) ───────────────────────────
async def test_patch_isolado_parcial_reflete_no_get_e_preserva_morfologia(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(
        client, h, project_id,
        organism_type="bacteria", colonia_forma="circular", colonia_cor="branca",
    )

    r = await client.patch(
        f"{PREFIX}/samples/{sample['id']}",
        json={
            "isolation_source": "rizosfera",
            "host_species": "Zea mays",
            "gram_stain": "negativa",
            "culture_medium": "TSA",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["isolation_source"] == "rizosfera"
    assert body["gram_stain"] == "negativa"

    r = await client.get(f"{PREFIX}/samples/{sample['id']}", headers=h)
    got = r.json()
    assert got["host_species"] == "Zea mays"
    assert got["culture_medium"] == "TSA"
    # Morfologia gravada antes continua lá.
    assert got["colonia_forma"] == "circular"
    assert got["colonia_cor"] == "branca"
    assert got["organism_type"] == "bacteria"


async def test_patch_gram_stain_fora_do_vocabulario_da_422(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)

    r = await client.patch(
        f"{PREFIX}/samples/{sample['id']}", json={"gram_stain": "roxa"}, headers=h
    )
    assert r.status_code == 422


async def test_patch_so_lat_sem_lon_da_422(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)

    r = await client.patch(
        f"{PREFIX}/samples/{sample['id']}", json={"lat": -18.2}, headers=h
    )
    assert r.status_code == 422


async def test_patch_lat_e_lon_atualiza_geom(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)
    assert sample["lat"] is None

    r = await client.patch(
        f"{PREFIX}/samples/{sample['id']}",
        json={"lat": -18.2, "lon": -43.6},
        headers=h,
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"{PREFIX}/samples/{sample['id']}", headers=h)
    got = r.json()
    assert got["lat"] == -18.2
    assert got["lon"] == -43.6

    # Ambos null limpa o ponto.
    r = await client.patch(
        f"{PREFIX}/samples/{sample['id']}", json={"lat": None, "lon": None}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["lat"] is None
    assert r.json()["lon"] is None


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


async def test_gene_aceita_fasta_colado_e_normaliza_sequencia(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)

    r = await client.post(
        f"{PREFIX}/samples/{sample['id']}/genes",
        json={
            "gene": "16S",
            "purpose": "identificacao",
            "sequence": ">NEBIM0001_16S\nACGT ACGT\n1 acgtn\n",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["sequence"] == "ACGTACGTACGTN"
    assert body["sequence_header"] == "NEBIM0001_16S"
    assert body["sequence_length"] == 13


async def test_gene_com_caractere_fora_do_alfabeto_da_422_listando_os_invalidos(
    client, org_admin
):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)

    r = await client.post(
        f"{PREFIX}/samples/{sample['id']}/genes",
        json={"gene": "16S", "purpose": "identificacao", "sequence": "ACGTXQ"},
        headers=h,
    )
    assert r.status_code == 422
    msg = r.text
    assert "X" in msg and "Q" in msg


async def test_patch_gene_com_resultado_blast(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)

    r = await client.post(
        f"{PREFIX}/samples/{sample['id']}/genes",
        json={"gene": "16S", "purpose": "identificacao"},
        headers=h,
    )
    gene_id = r.json()["id"]

    r = await client.patch(
        f"{PREFIX}/samples/{sample['id']}/genes/{gene_id}",
        json={
            "blast_top_hit": "Bacillus velezensis strain FZB42",
            "blast_identity_pct": 99.3,
            "blast_coverage_pct": 100,
            "blast_hit_accession": "NR_075005.2",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["blast_top_hit"] == "Bacillus velezensis strain FZB42"
    assert body["blast_identity_pct"] == 99.3
    assert body["blast_coverage_pct"] == 100
    assert body["blast_hit_accession"] == "NR_075005.2"
    assert body["gene"] == "16S"  # não foi tocado

    r = await client.patch(
        f"{PREFIX}/samples/{sample['id']}/genes/{gene_id}",
        json={"blast_identity_pct": 101},
        headers=h,
    )
    assert r.status_code == 422


async def test_delete_gene_e_teste_somem_da_listagem(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)

    g = await client.post(
        f"{PREFIX}/samples/{sample['id']}/genes",
        json={"gene": "16S", "purpose": "identificacao"},
        headers=h,
    )
    t = await client.post(
        f"{PREFIX}/samples/{sample['id']}/tests",
        json={"test_name": "Catalase", "result": "+"},
        headers=h,
    )
    gene_id, test_id = g.json()["id"], t.json()["id"]

    r = await client.delete(f"{PREFIX}/samples/{sample['id']}/genes/{gene_id}", headers=h)
    assert r.status_code == 204, r.text
    r = await client.delete(f"{PREFIX}/samples/{sample['id']}/tests/{test_id}", headers=h)
    assert r.status_code == 204, r.text

    r = await client.get(f"{PREFIX}/samples/{sample['id']}/genes", headers=h)
    assert r.json() == []
    r = await client.get(f"{PREFIX}/samples/{sample['id']}/tests", headers=h)
    assert r.json() == []


async def test_delete_subrecurso_com_id_de_outra_amostra_da_404(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample_a = await _make_sample(client, h, project_id, code="BAC-A")
    sample_b = await _make_sample(client, h, project_id, code="BAC-B")

    g = await client.post(
        f"{PREFIX}/samples/{sample_a['id']}/genes",
        json={"gene": "16S", "purpose": "identificacao"},
        headers=h,
    )
    t = await client.post(
        f"{PREFIX}/samples/{sample_a['id']}/tests",
        json={"test_name": "Catalase", "result": "+"},
        headers=h,
    )
    gene_id, test_id = g.json()["id"], t.json()["id"]

    # Ids válidos, mas pela URL da amostra B: não pertencem a ela → 404.
    r = await client.delete(f"{PREFIX}/samples/{sample_b['id']}/genes/{gene_id}", headers=h)
    assert r.status_code == 404
    r = await client.delete(f"{PREFIX}/samples/{sample_b['id']}/tests/{test_id}", headers=h)
    assert r.status_code == 404
    r = await client.patch(
        f"{PREFIX}/samples/{sample_b['id']}/genes/{gene_id}",
        json={"blast_top_hit": "x"},
        headers=h,
    )
    assert r.status_code == 404

    # E continuam existindo na amostra A.
    r = await client.get(f"{PREFIX}/samples/{sample_a['id']}/genes", headers=h)
    assert len(r.json()) == 1


# ── Alíquotas ───────────────────────────────────────────────────────────
async def test_aliquotas_crud_e_rotulo_unico_por_amostra(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)
    project_id = await _make_project(client, h)
    sample = await _make_sample(client, h, project_id)
    url = f"{PREFIX}/samples/{sample['id']}/aliquots"

    r1 = await client.post(
        url,
        json={"label": "R1", "storage_method": "glicerol_-80", "freezer": "F1", "box": "B3"},
        headers=h,
    )
    assert r1.status_code == 201, r1.text
    assert r1.json()["status"] == "disponivel"
    assert r1.json()["storage_method"] == "glicerol_-80"

    r2 = await client.post(url, json={"label": "R2", "storage_method": "liofilizado"}, headers=h)
    assert r2.status_code == 201, r2.text

    dup = await client.post(url, json={"label": "R1", "storage_method": "placa_4c"}, headers=h)
    assert dup.status_code == 409
    assert "R1" in dup.json()["detail"]

    r = await client.get(url, headers=h)
    assert [a["label"] for a in r.json()] == ["R1", "R2"]

    aliquot_id = r1.json()["id"]
    r = await client.patch(f"{url}/{aliquot_id}", json={"status": "consumida"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "consumida"
    assert r.json()["freezer"] == "F1"  # não foi tocado

    r = await client.delete(f"{url}/{aliquot_id}", headers=h)
    assert r.status_code == 204
    r = await client.get(url, headers=h)
    assert [a["label"] for a in r.json()] == ["R2"]


async def test_aliquota_de_outra_org_nao_vaza_e_viewer_nao_cria(client, db):
    org_a = await make_org(db, slug=rand_slug())
    user_a = await make_user(db)
    await make_member(db, org_a, user_a, "org_admin")
    viewer_a = await make_user(db)
    await make_member(db, org_a, viewer_a, "viewer")

    org_b = await make_org(db, slug=rand_slug())
    user_b = await make_user(db)
    await make_member(db, org_b, user_b, "org_admin")

    ha, hb = auth(user_a), auth(user_b)
    project_a = await _make_project(client, ha)
    sample_a = await _make_sample(client, ha, project_a)
    url = f"{PREFIX}/samples/{sample_a['id']}/aliquots"

    r = await client.post(url, json={"label": "R1", "storage_method": "glicerol_-80"}, headers=ha)
    assert r.status_code == 201, r.text

    # Org B não enxerga nem a amostra.
    r = await client.get(url, headers=hb)
    assert r.status_code == 404

    # viewer da própria org lê, mas não cria.
    r = await client.get(url, headers=auth(viewer_a, "viewer"))
    assert r.status_code == 200
    r = await client.post(
        url, json={"label": "R2", "storage_method": "glicerol_-80"},
        headers=auth(viewer_a, "viewer"),
    )
    assert r.status_code == 403


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
