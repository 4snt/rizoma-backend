"""Integração: gating de autenticação nos endpoints de projeto.

Sem Bearer, o HTTPBearer rejeita antes de qualquer acesso ao banco (403).
"""
from uuid import uuid4


async def test_create_project_requires_auth(client):
    resp = await client.post("/api/v1/projects/", json={
        "code": "X", "name": "Y", "marker_type": "16S", "analyses": [],
    })
    assert resp.status_code == 403


async def test_update_project_requires_auth(client):
    resp = await client.put(f"/api/v1/projects/{uuid4()}", json={"name": "Z"})
    assert resp.status_code == 403


async def test_delete_project_requires_auth(client):
    resp = await client.delete(f"/api/v1/projects/{uuid4()}")
    assert resp.status_code == 403


async def test_admin_users_requires_auth(client):
    resp = await client.get("/api/v1/admin/users")
    assert resp.status_code == 403
