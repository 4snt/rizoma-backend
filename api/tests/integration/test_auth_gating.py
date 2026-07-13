"""Integração: gating de autenticação nos endpoints v2.

Sem Bearer, a rota rejeita antes de qualquer acesso ao banco. Por isso este
teste roda sem Postgres — é um smoke test de que as rotas protegidas não abrem
sem autenticação. O v2 responde 401 (não autenticado); 403 fica reservado para
autenticado-porém-sem-permissão.
"""
from uuid import uuid4

# HTTPBearer sem credencial → 401. Alguns setups devolvem 403; aceitamos ambos
# para o teste checar o que importa: a rota NÃO abre sem token.
UNAUTH = {401, 403}


async def test_list_projects_requires_auth(client):
    resp = await client.get("/api/v2/lims/projects")
    assert resp.status_code in UNAUTH


async def test_create_customer_requires_auth(client):
    resp = await client.post("/api/v2/lims/customers", json={"name": "X"})
    assert resp.status_code in UNAUTH


async def test_enqueue_job_requires_auth(client):
    resp = await client.post(
        "/api/v2/jobs/enqueue",
        json={"project_id": str(uuid4()), "job_type": "deseq2"},
    )
    assert resp.status_code in UNAUTH


async def test_me_requires_auth(client):
    resp = await client.get("/api/v2/identity/me")
    assert resp.status_code in UNAUTH
