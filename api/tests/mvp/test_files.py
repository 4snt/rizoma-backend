"""Catálogo de arquivos — testes contra MinIO e Postgres REAIS.

Mockar o storage aqui não provaria nada: o ponto do /confirm é justamente
descobrir que o objeto NÃO está lá. Um mock sempre diria que está.
"""
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text

from app.core.security import create_access_token
from app.modules.files.router import router as files_router
from app.shared import storage
from app.shared.ids import new_id

from .conftest import make_member, make_org, make_user

BASE = "/api/v2/files"


@pytest_asyncio.fixture
async def app_client():
    app = FastAPI()
    app.include_router(files_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def scenario(db):
    """Org + usuário org_admin + projeto, semeados com o papel de sistema."""
    try:
        storage.ensure_bucket()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"MinIO indisponível: {exc}")

    org_id = await make_org(db)
    user_id = await make_user(db)
    await make_member(db, org_id, user_id, "org_admin")

    project_id = new_id()
    async with db() as s:
        async with s.begin():
            await s.execute(
                text(
                    "INSERT INTO projects (id, organization_id, code, name, created_by) "
                    "VALUES (:i, :o, :c, :n, :u)"
                ),
                {
                    "i": str(project_id),
                    "o": str(org_id),
                    "c": f"P-{str(project_id)[:8]}",
                    "n": "Projeto Teste",
                    "u": str(user_id),
                },
            )

    token = create_access_token(str(user_id), "org_admin")
    yield {
        "org_id": org_id,
        "user_id": user_id,
        "project_id": project_id,
        "headers": {"Authorization": f"Bearer {token}", "X-Organization": str(org_id)},
    }


def _upload_to_minio(presigned: dict, content: bytes, filename: str) -> httpx.Response:
    """O upload REAL: multipart POST direto no MinIO, exatamente como o browser
    faria. A API não vê um byte disso."""
    return httpx.post(
        presigned["upload_url"],
        data=presigned["fields"],
        files={"file": (filename, content, presigned["fields"].get("Content-Type"))},
        timeout=30,
    )


async def test_presign_upload_confirm_roundtrip(app_client, scenario, db):
    content = b"@SEQ1\nACGTACGTACGT\n+\nIIIIIIIIIIII\n"

    r = await app_client.post(
        f"{BASE}/presign",
        json={
            "project_id": str(scenario["project_id"]),
            "category": "fastq_r1",
            "original_name": "amostra_R1.fastq",
            "mime_type": "text/plain",
        },
        headers=scenario["headers"],
    )
    assert r.status_code == 201, r.text
    presigned = r.json()
    file_id = presigned["file_id"]

    async with db() as s:
        status_before = (
            await s.execute(
                text("SELECT upload_status FROM files WHERE id = :i"), {"i": file_id}
            )
        ).scalar_one()
    assert status_before == "pending"

    up = _upload_to_minio(presigned, content, "amostra_R1.fastq")
    assert up.status_code in (200, 204), up.text

    r = await app_client.post(
        f"{BASE}/{file_id}/confirm", json={"sha256": "a" * 64}, headers=scenario["headers"]
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["upload_status"] == "uploaded"
    assert body["size_bytes"] == len(content)
    assert body["sha256"] == "a" * 64

    # download presigned funciona de verdade
    r = await app_client.get(f"{BASE}/{file_id}/download", headers=scenario["headers"])
    assert r.status_code == 200
    got = httpx.get(r.json()["url"], timeout=30)
    assert got.status_code == 200
    assert got.content == content

    # listagem
    r = await app_client.get(
        f"{BASE}/", params={"project_id": str(scenario["project_id"])},
        headers=scenario["headers"],
    )
    assert r.status_code == 200
    assert [f["id"] for f in r.json()] == [file_id]

    # delete remove do MinIO e do catálogo
    r = await app_client.delete(f"{BASE}/{file_id}", headers=scenario["headers"])
    assert r.status_code == 204
    assert storage.head(presigned["storage_key"]) is None


async def test_confirm_sem_upload_marca_failed(app_client, scenario, db):
    """O confirm faz HEAD no storage. Sem isso, o catálogo registraria um arquivo
    que não existe — e o worker só descobriria 20 minutos depois."""
    r = await app_client.post(
        f"{BASE}/presign",
        json={
            "project_id": str(scenario["project_id"]),
            "category": "phyloseq",
            "original_name": "nunca_enviado.rds",
        },
        headers=scenario["headers"],
    )
    assert r.status_code == 201
    file_id = r.json()["file_id"]

    r = await app_client.post(f"{BASE}/{file_id}/confirm", json={}, headers=scenario["headers"])
    assert r.status_code == 400
    assert "storage" in r.json()["detail"].lower()

    async with db() as s:
        st = (
            await s.execute(
                text("SELECT upload_status FROM files WHERE id = :i"), {"i": file_id}
            )
        ).scalar_one()
    assert st == "failed"


# ── Vínculo arquivo ↔ gene (FASTA/cromatograma do 16S) ────────────────────
async def _seed_sample_with_gene(db, scenario, code: str) -> tuple[str, str]:
    """Amostra + gene direto no banco (papel de sistema) — o cenário aqui é
    o catálogo de arquivos, não o fluxo do LIMS."""
    sample_id, gene_id = new_id(), new_id()
    async with db() as s:
        async with s.begin():
            await s.execute(
                text(
                    "INSERT INTO samples (id, organization_id, project_id, code, matrix, status) "
                    "VALUES (:i, :o, :p, :c, 'cultura_microbiana', 'planned')"
                ),
                {
                    "i": str(sample_id),
                    "o": str(scenario["org_id"]),
                    "p": str(scenario["project_id"]),
                    "c": code,
                },
            )
            await s.execute(
                text(
                    "INSERT INTO sample_genes (id, organization_id, sample_id, gene, purpose) "
                    "VALUES (:i, :o, :s, '16S', 'identificacao')"
                ),
                {"i": str(gene_id), "o": str(scenario["org_id"]), "s": str(sample_id)},
            )
    return str(sample_id), str(gene_id)


async def test_presign_fasta_vinculado_a_gene(app_client, scenario, db):
    sample_id, gene_id = await _seed_sample_with_gene(db, scenario, "BAC-01")
    _, other_gene_id = await _seed_sample_with_gene(db, scenario, "BAC-02")

    r = await app_client.post(
        f"{BASE}/presign",
        json={
            "project_id": str(scenario["project_id"]),
            "sample_id": sample_id,
            "sample_gene_id": gene_id,
            "category": "fasta",
            "original_name": "BAC-01_16S.fasta",
            "mime_type": "text/plain",
        },
        headers=scenario["headers"],
    )
    assert r.status_code == 201, r.text
    file_id = r.json()["file_id"]

    # Outro arquivo da mesma amostra, sem gene — não deve aparecer no filtro.
    r = await app_client.post(
        f"{BASE}/presign",
        json={
            "project_id": str(scenario["project_id"]),
            "sample_id": sample_id,
            "category": "colony_photo",
            "original_name": "BAC-01_placa.jpg",
        },
        headers=scenario["headers"],
    )
    assert r.status_code == 201, r.text

    r = await app_client.get(
        f"{BASE}/", params={"sample_gene_id": gene_id}, headers=scenario["headers"]
    )
    assert r.status_code == 200
    files = r.json()
    assert [f["id"] for f in files] == [file_id]
    assert files[0]["sample_gene_id"] == gene_id
    assert files[0]["category"] == "fasta"

    # Gene de OUTRA amostra: 404, não vincula.
    r = await app_client.post(
        f"{BASE}/presign",
        json={
            "project_id": str(scenario["project_id"]),
            "sample_id": sample_id,
            "sample_gene_id": other_gene_id,
            "category": "chromatogram",
            "original_name": "errado.ab1",
        },
        headers=scenario["headers"],
    )
    assert r.status_code == 404
    assert "Gene" in r.json()["detail"]

    # sample_gene_id sem sample_id: 422.
    r = await app_client.post(
        f"{BASE}/presign",
        json={
            "project_id": str(scenario["project_id"]),
            "sample_gene_id": gene_id,
            "category": "fasta",
            "original_name": "sem_amostra.fasta",
        },
        headers=scenario["headers"],
    )
    assert r.status_code == 422
