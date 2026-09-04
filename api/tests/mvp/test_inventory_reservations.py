"""Testes de agenda de uso de equipamento (reservas) — tcc-rizoma#9.

Banco real. Sobe um FastAPI local só com o router de inventory, mesmo padrão
de test_lims.py/test_lims_biological.py.
"""
import httpx
import pytest_asyncio
from fastapi import FastAPI

from app.core.security import create_access_token
from app.modules.inventory.router import router as inventory_router
from tests.mvp.conftest import make_member, make_org, make_user, rand_slug

PREFIX = "/api/v2/inventory"


@pytest_asyncio.fixture
async def client():
    app = FastAPI()
    app.include_router(inventory_router, prefix=PREFIX)
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


async def _make_equipment(client, headers, name="Termociclador") -> str:
    r = await client.post(f"{PREFIX}/equipment", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_reservation_roundtrip(client, org_admin):
    org_id, user_id = org_admin
    headers = auth(user_id)
    equipment_id = await _make_equipment(client, headers)

    r = await client.post(
        f"{PREFIX}/equipment/{equipment_id}/reservations",
        json={"starts_at": "2030-01-01T10:00:00Z", "ends_at": "2030-01-01T12:00:00Z", "notes": "PCR"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["notes"] == "PCR"
    reservation_id = body["id"]

    r = await client.get(f"{PREFIX}/equipment/{equipment_id}/reservations", headers=headers)
    assert r.status_code == 200
    assert [x["id"] for x in r.json()] == [reservation_id]

    r = await client.post(
        f"{PREFIX}/equipment/{equipment_id}/reservations/{reservation_id}/cancel", headers=headers
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    # Cancelar de novo (já cancelada) é 404 — não existe mais reserva
    # 'confirmed' com esse id pra cancelar.
    r = await client.post(
        f"{PREFIX}/equipment/{equipment_id}/reservations/{reservation_id}/cancel", headers=headers
    )
    assert r.status_code == 404


async def test_overlapping_reservation_conflicts(client, org_admin):
    org_id, user_id = org_admin
    headers = auth(user_id)
    equipment_id = await _make_equipment(client, headers)

    r = await client.post(
        f"{PREFIX}/equipment/{equipment_id}/reservations",
        json={"starts_at": "2030-02-01T10:00:00Z", "ends_at": "2030-02-01T12:00:00Z"},
        headers=headers,
    )
    assert r.status_code == 201, r.text

    # Sobrepõe no meio do intervalo já reservado.
    r = await client.post(
        f"{PREFIX}/equipment/{equipment_id}/reservations",
        json={"starts_at": "2030-02-01T11:00:00Z", "ends_at": "2030-02-01T13:00:00Z"},
        headers=headers,
    )
    assert r.status_code == 409, r.text

    # Não sobrepõe (começa exatamente quando o primeiro termina) — permitido.
    r = await client.post(
        f"{PREFIX}/equipment/{equipment_id}/reservations",
        json={"starts_at": "2030-02-01T12:00:00Z", "ends_at": "2030-02-01T13:00:00Z"},
        headers=headers,
    )
    assert r.status_code == 201, r.text


async def test_cancelled_reservation_frees_the_slot(client, org_admin):
    org_id, user_id = org_admin
    headers = auth(user_id)
    equipment_id = await _make_equipment(client, headers)

    r = await client.post(
        f"{PREFIX}/equipment/{equipment_id}/reservations",
        json={"starts_at": "2030-03-01T10:00:00Z", "ends_at": "2030-03-01T12:00:00Z"},
        headers=headers,
    )
    reservation_id = r.json()["id"]

    r = await client.post(
        f"{PREFIX}/equipment/{equipment_id}/reservations/{reservation_id}/cancel", headers=headers
    )
    assert r.status_code == 200

    # Mesmo horário, mas a reserva anterior foi cancelada — não deveria dar conflito.
    r = await client.post(
        f"{PREFIX}/equipment/{equipment_id}/reservations",
        json={"starts_at": "2030-03-01T10:00:00Z", "ends_at": "2030-03-01T12:00:00Z"},
        headers=headers,
    )
    assert r.status_code == 201, r.text


async def test_ends_before_starts_is_rejected(client, org_admin):
    org_id, user_id = org_admin
    headers = auth(user_id)
    equipment_id = await _make_equipment(client, headers)

    r = await client.post(
        f"{PREFIX}/equipment/{equipment_id}/reservations",
        json={"starts_at": "2030-04-01T12:00:00Z", "ends_at": "2030-04-01T10:00:00Z"},
        headers=headers,
    )
    assert r.status_code == 400


async def test_viewer_cannot_reserve(client, org_admin, db):
    org_id, admin_id = org_admin
    equipment_id = await _make_equipment(client, auth(admin_id))

    viewer_id = await make_user(db)
    await make_member(db, org_id, viewer_id, "viewer")

    r = await client.post(
        f"{PREFIX}/equipment/{equipment_id}/reservations",
        json={"starts_at": "2030-05-01T10:00:00Z", "ends_at": "2030-05-01T12:00:00Z"},
        headers=auth(viewer_id, "viewer"),
    )
    assert r.status_code == 403
