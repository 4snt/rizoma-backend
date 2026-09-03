"""Testes de interoperabilidade: webhooks + import/export CSV de amostras.

Cobre especialmente a checagem de papel do CSV, que faltava: `export_samples_csv`
e `import_samples_csv` chamam `lims_service` direto (não passam pelo router de
lims, onde normalmente mora o `ctx.require()`), então sem checagem própria
qualquer membro — até `viewer`/`client` — conseguia exportar/importar amostras
sem a permissão `sample:read`/`sample:write`.
"""
import httpx
import pytest_asyncio
from fastapi import FastAPI

from app.core.security import create_access_token
from app.modules.interop.router import router as interop_router
from app.modules.lims.router import router as lims_router
from app.shared.ids import new_id
from tests.mvp.conftest import make_member, make_org, make_user, rand_slug

LIMS_PREFIX = "/api/v2/lims"
INTEROP_PREFIX = "/api/v2/interop"


@pytest_asyncio.fixture
async def client():
    app = FastAPI()
    app.include_router(lims_router, prefix=LIMS_PREFIX)
    app.include_router(interop_router, prefix=INTEROP_PREFIX)
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
    r = await client.post(
        f"{LIMS_PREFIX}/projects",
        json={"code": f"P-{new_id().hex[:6]}", "name": "Interop"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── Webhooks ──────────────────────────────────────────────────────────────


async def test_org_admin_cria_lista_e_apaga_webhook(client, org_admin):
    _, user_id = org_admin
    h = auth(user_id)

    r = await client.post(
        f"{INTEROP_PREFIX}/webhooks",
        json={"url": "https://example.org/hook", "event_types": ["sample.created"]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    webhook_id = r.json()["id"]
    assert "secret" in r.json()

    r = await client.get(f"{INTEROP_PREFIX}/webhooks", headers=h)
    assert r.status_code == 200
    assert any(w["id"] == webhook_id for w in r.json())

    r = await client.delete(f"{INTEROP_PREFIX}/webhooks/{webhook_id}", headers=h)
    assert r.status_code == 204


async def test_papel_sem_member_write_nao_cria_webhook(client, org_admin, db):
    org_id, _ = org_admin
    tech = await make_user(db)
    await make_member(db, org_id, tech, "lab_tech")  # não tem member:write

    r = await client.post(
        f"{INTEROP_PREFIX}/webhooks",
        json={"url": "https://example.org/hook", "event_types": ["sample.created"]},
        headers=auth(tech, "lab_tech"),
    )
    assert r.status_code == 403


# ── Export/import de amostras (CSV) — a checagem que faltava ─────────────


async def test_viewer_nao_exporta_csv_sem_sample_read_de_verdade(client, org_admin, db):
    """`viewer` TEM sample:read no PERMISSIONS — este teste é o caminho feliz
    pra confirmar que a checagem nova não quebrou quem devia poder."""
    org_id, admin_id = org_admin
    project_id = await _make_project(client, auth(admin_id))

    viewer = await make_user(db)
    await make_member(db, org_id, viewer, "viewer")

    r = await client.get(
        f"{INTEROP_PREFIX}/projects/{project_id}/samples/export",
        headers=auth(viewer, "viewer"),
    )
    assert r.status_code == 200
    assert "code,matrix" in r.text


async def test_client_sem_sample_read_nao_exporta_csv(client, org_admin, db):
    """`client` (acesso externo, só laudo) não tem sample:read — antes do
    fix, esta chamada devolvia 200 com todas as amostras do projeto."""
    org_id, admin_id = org_admin
    project_id = await _make_project(client, auth(admin_id))

    external = await make_user(db)
    await make_member(db, org_id, external, "client")

    r = await client.get(
        f"{INTEROP_PREFIX}/projects/{project_id}/samples/export",
        headers=auth(external, "client"),
    )
    assert r.status_code == 403


async def test_client_sem_sample_write_nao_importa_csv(client, org_admin, db):
    """Idem para import — antes do fix, `client` conseguia criar amostras
    em massa via CSV mesmo sem sample:write."""
    org_id, admin_id = org_admin
    project_id = await _make_project(client, auth(admin_id))

    external = await make_user(db)
    await make_member(db, org_id, external, "client")

    csv_body = "code,matrix\nS-CSV-01,solo\n"
    r = await client.post(
        f"{INTEROP_PREFIX}/projects/{project_id}/samples/import",
        files={"file": ("samples.csv", csv_body, "text/csv")},
        headers=auth(external, "client"),
    )
    assert r.status_code == 403


async def test_field_tech_importa_csv_com_sample_write(client, org_admin, db):
    """Caminho feliz do import: field_tech tem sample:write."""
    org_id, admin_id = org_admin
    project_id = await _make_project(client, auth(admin_id))

    field = await make_user(db)
    await make_member(db, org_id, field, "field_tech")

    csv_body = "code,matrix\nS-CSV-01,solo\n"
    r = await client.post(
        f"{INTEROP_PREFIX}/projects/{project_id}/samples/import",
        files={"file": ("samples.csv", csv_body, "text/csv")},
        headers=auth(field, "field_tech"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1
