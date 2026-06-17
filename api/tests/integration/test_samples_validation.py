"""Integração: validação do upload de par FASTQ (antes de tocar o banco).

O endpoint exige que o R1 contenha '_R1_' no nome — a checagem acontece antes
de qualquer consulta ao banco, então retorna 422 sem Postgres.
"""
from uuid import uuid4


async def test_upload_pair_rejects_bad_r1_name(client):
    files = {
        "r1": ("amostra_sem_padrao.fastq.gz", b"@seq\nACGT\n+\nIIII\n", "application/gzip"),
        "r2": ("amostra_sem_padrao.fastq.gz", b"@seq\nACGT\n+\nIIII\n", "application/gzip"),
    }
    data = {"project_id": str(uuid4())}
    resp = await client.post("/api/v1/samples/upload-pair", files=files, data=data)
    assert resp.status_code == 422
    assert "_R1_" in resp.json()["detail"]
