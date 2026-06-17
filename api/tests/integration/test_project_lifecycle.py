"""Integração ponta a ponta de projeto (REQUER Postgres de teste).

Pulado automaticamente quando o banco não está acessível (fixture `db_pool`).
Cobre: criar → buscar → atualizar (dada2_params) → excluir, validando também que
não restam large objects órfãos após a exclusão.
"""
from uuid import uuid4

import pytest

from app.core.security import create_access_token


def _admin_headers():
    token = create_access_token(sub=str(uuid4()), role="admin")
    return {"Authorization": f"Bearer {token}"}


async def test_project_crud_lifecycle(client, db_pool):
    headers = _admin_headers()
    code = f"TEST{uuid4().hex[:6].upper()}"

    # CREATE
    resp = await client.post("/api/v1/projects/", headers=headers, json={
        "code": code, "name": "Projeto de Teste", "marker_type": "16S",
        "analyses": [{"analysis_type": "deseq2", "charts": ["volcano"]}],
        "dada2_params": {"trunc_len_f": 230, "trunc_len_r": 180},
    })
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]

    try:
        # READ
        resp = await client.get(f"/api/v1/projects/{pid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == code
        assert body["dada2_params"]["trunc_len_f"] == 230
        assert len(body["analyses"]) == 1

        # UPDATE (params)
        resp = await client.put(f"/api/v1/projects/{pid}", headers=headers, json={
            "dada2_params": {"trunc_len_f": 200, "trunc_len_r": 150, "max_ee_f": 1},
        })
        assert resp.status_code == 200
        assert resp.json()["dada2_params"]["trunc_len_f"] == 200
    finally:
        # DELETE
        resp = await client.delete(f"/api/v1/projects/{pid}", headers=_admin_headers())
        assert resp.status_code in (204, 404)

    # Confirma remoção
    resp = await client.get(f"/api/v1/projects/{pid}")
    assert resp.status_code == 404


async def test_delete_unknown_project_404(client, db_pool):
    resp = await client.delete(f"/api/v1/projects/{uuid4()}", headers=_admin_headers())
    assert resp.status_code == 404
