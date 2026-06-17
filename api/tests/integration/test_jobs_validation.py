"""Integração: validação de entrada do enqueue (antes de tocar o banco)."""
from uuid import uuid4


async def test_invalid_job_type_returns_422(client):
    resp = await client.post("/api/v1/jobs/enqueue", json={
        "project_id": str(uuid4()),
        "job_type": "tipo_inexistente",
        "payload": {},
    })
    assert resp.status_code == 422
    assert "job_type" in resp.json()["detail"]


async def test_malformed_body_returns_422(client):
    # project_id ausente → validação Pydantic (422)
    resp = await client.post("/api/v1/jobs/enqueue", json={"job_type": "deseq2"})
    assert resp.status_code == 422
