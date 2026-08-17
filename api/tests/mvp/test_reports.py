"""Laudos: snapshot, PDF assinado no MinIO e verificação pública por hash.

MinIO REAL. O teste baixa o PDF de volta do bucket — um mock de storage provaria
que o mock guarda bytes, não que o laudo existe.
"""
import hashlib

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text

from app.core.config import settings
from app.core.security import create_access_token
from app.modules.laboratory.router import router as lab_router
from app.modules.reports import service as reports_service
from app.modules.reports.pdf import build_report_pdf
from app.modules.reports.router import router as reports_router
from app.shared import storage
from app.shared.ids import new_id

from .conftest import make_member, make_org, make_user, rand_email, rand_slug
from .test_laboratory import purge_lab_data

LAB = "/api/v2/lab"
V2 = "/api/v2"


@pytest_asyncio.fixture
async def client():
    """Sobrescreve o `client` do conftest (que monta o router de identidade)."""
    app = FastAPI()
    app.include_router(lab_router)
    app.include_router(reports_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(autouse=True)
async def _dispose_system_engine():
    """O engine BYPASSRLS do /verify é global e lazy; suas conexões ficam presas
    ao event loop deste teste."""
    yield
    await reports_service.dispose_system_engine()


@pytest_asyncio.fixture
async def scenario(db):
    """Org + cliente + projeto + amostra + 2 usuários + 1 job concluído.

    O job existe para que o laudo tenha uma seção de bioinformática de verdade.
    """
    org_id = await make_org(db, slug=rand_slug(), name="Laboratório Rizoma UFVJM")
    producer = await make_user(db, name="Ana Produtora")
    signer = await make_user(db, name="Bruno Responsável Técnico")
    await make_member(db, org_id, producer, role="tech_responsible")
    await make_member(db, org_id, signer, role="org_admin")

    customer_id, project_id, sample_id = new_id(), new_id(), new_id()
    job_id, ares_id = new_id(), new_id()
    customer_email = rand_email()
    async with db() as s:
        async with s.begin():
            # "Pesquisador"/"cliente" agora é sempre um organization_member —
            # ver ADR de fusão Customer -> User. E-mail via rand_email(): tem
            # o prefixo que o teardown do conftest sabe limpar; um e-mail
            # literal ficaria pra sempre no banco (violação global de
            # users.email já na segunda vez que este teste rodasse).
            await s.execute(
                text("INSERT INTO users (id, email, name) VALUES (:i, :e, :n)"),
                {"i": str(customer_id), "e": customer_email,
                 "n": f"Fazenda {str(customer_id)[:6]}"},
            )
            await s.execute(
                text(
                    "INSERT INTO organization_members (id, organization_id, user_id, role) "
                    "VALUES (:i, :o, :u, 'client')"
                ),
                {"i": str(new_id()), "o": str(org_id), "u": str(customer_id)},
            )
            await s.execute(
                text(
                    "INSERT INTO projects (id, organization_id, customer_user_id, code, name, "
                    "description, marker_type, status) "
                    "VALUES (:i, :o, :c, :code, 'INOVAHERB', :d, 'ITS', 'in_progress')"
                ),
                {"i": str(project_id), "o": str(org_id), "c": str(customer_id),
                 "code": f"PRJ-{str(project_id)[:8]}",
                 "d": "Micobioma rizosférico de plantas medicinais."},
            )
            await s.execute(
                text(
                    "INSERT INTO samples (id, organization_id, project_id, code, matrix, "
                    "treatment_group, replicate, status) "
                    "VALUES (:i, :o, :p, :c, 'solo', 'controle', 1, 'received')"
                ),
                {"i": str(sample_id), "o": str(org_id), "p": str(project_id),
                 "c": f"AM-{str(sample_id)[:8]}"},
            )
            await s.execute(
                text(
                    "INSERT INTO pipeline_jobs (id, organization_id, project_id, job_type, status) "
                    "VALUES (:i, :o, :p, 'ancombc2', 'completed')"
                ),
                {"i": str(job_id), "o": str(org_id), "p": str(project_id)},
            )
            await s.execute(
                text(
                    "INSERT INTO analysis_results (id, organization_id, job_id, analysis_type, "
                    "result_data) VALUES (:i, :o, :j, 'ancombc2', CAST(:d AS jsonb))"
                ),
                {"i": str(ares_id), "o": str(org_id), "j": str(job_id),
                 "d": '{"taxa_significativos": 12, "metodo": "ANCOM-BC2"}'},
            )

    def headers(user_id, role):
        return {
            "Authorization": f"Bearer {create_access_token(str(user_id), role)}",
            "X-Organization": str(org_id),
        }

    yield {
        "org_id": org_id,
        "project_id": project_id,
        "sample_id": sample_id,
        "producer": producer,
        "signer": signer,
        "customer_email": customer_email,
        "producer_h": headers(producer, "tech_responsible"),
        "signer_h": headers(signer, "org_admin"),
    }

    await purge_lab_data(org_id)


async def _approved_result(client, sc) -> None:
    """Resultado abaixo do LOD, produzido por um e aprovado por OUTRO.

    Abaixo do LOD de propósito: é o caso que o laudo mais facilmente falsifica.
    """
    r = await client.post(
        f"{LAB}/samples/{sc['sample_id']}/results",
        json={"analyte": "Cádmio", "method": "ICP-MS", "value_numeric": 0.01,
              "unit": "mg/kg", "lod": 0.05, "loq": 0.15, "uncertainty": 0.002},
        headers=sc["producer_h"],
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    rev = await client.post(
        f"{LAB}/results/{rid}/review", json={"status": "approved"}, headers=sc["signer_h"]
    )
    assert rev.status_code == 200, rev.text


async def test_cria_laudo_draft_com_snapshot(client, scenario):
    await _approved_result(client, scenario)

    r = await client.post(
        f"{V2}/projects/{scenario['project_id']}/reports",
        json={"title": "Laudo de Micobioma — INOVAHERB"},
        headers=scenario["signer_h"],
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "draft"
    assert body["version"] == 1
    assert body["sha256"] is None

    content = body["content"]
    assert content["project"]["name"] == "INOVAHERB"
    assert content["customer"]["contact_email"] == scenario["customer_email"]
    assert len(content["samples"]) == 1
    # Só o resultado APROVADO entra, e entra como "<0.05" — não como 0, não como null.
    assert len(content["results"]) == 1
    assert content["results"][0]["below_lod"] is True
    assert content["results"][0]["display_value"] == "<0.05"
    assert content["results"][0]["unit"] == "mg/kg"
    # Bioinformática do job concluído.
    assert content["bioinformatics"][0]["analysis_type"] == "ancombc2"


async def test_laudo_ignora_resultado_nao_aprovado(client, scenario):
    """Resultado apenas 'submitted' não entra num laudo. Um laudo não carrega rascunho."""
    r = await client.post(
        f"{LAB}/samples/{scenario['sample_id']}/results",
        json={"analyte": "Chumbo", "value_numeric": 3.0, "unit": "mg/kg"},
        headers=scenario["producer_h"],
    )
    assert r.status_code == 201

    rep = await client.post(
        f"{V2}/projects/{scenario['project_id']}/reports",
        json={"title": "Laudo sem aprovados"},
        headers=scenario["signer_h"],
    )
    assert rep.json()["content"]["results"] == []


async def test_assina_laudo_gera_pdf_no_minio(client, scenario, db):
    await _approved_result(client, scenario)

    created = await client.post(
        f"{V2}/projects/{scenario['project_id']}/reports",
        json={"title": "Laudo de Micobioma — INOVAHERB"},
        headers=scenario["signer_h"],
    )
    report_id = created.json()["id"]

    r = await client.post(f"{V2}/reports/{report_id}/sign", headers=scenario["signer_h"])
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["status"] == "published"
    assert body["signed_by"] == str(scenario["signer"])
    assert body["signed_at"] is not None
    assert body["sha256"] and len(body["sha256"]) == 64
    assert body["download_url"], "laudo publicado precisa de URL de download"

    # O PDF existe MESMO no MinIO.
    meta = storage.head(body["storage_key"])
    assert meta is not None, "PDF não chegou ao bucket"
    assert meta["size_bytes"] > 1000

    # E os bytes guardados são exatamente os que o sha256 registrado descreve.
    obj = storage.internal_client().get_object(
        Bucket=settings.s3_bucket, Key=body["storage_key"]
    )
    pdf_bytes = obj["Body"].read()
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000
    assert hashlib.sha256(pdf_bytes).hexdigest() == body["sha256"]

    storage.delete(body["storage_key"])


async def test_verify_publico_aceita_hash_correto(client, scenario):
    await _approved_result(client, scenario)
    created = await client.post(
        f"{V2}/projects/{scenario['project_id']}/reports",
        json={"title": "Laudo verificável"},
        headers=scenario["signer_h"],
    )
    report_id = created.json()["id"]
    signed = (
        await client.post(f"{V2}/reports/{report_id}/sign", headers=scenario["signer_h"])
    ).json()

    # SEM cabeçalho de autenticação — é o destino do QR Code impresso.
    r = await client.get(f"{V2}/reports/{report_id}/verify", params={"hash": signed["sha256"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is True
    assert body["code"] == signed["code"]
    assert body["version"] == 1
    assert body["project"] == "INOVAHERB"
    assert body["organization"] == "Laboratório Rizoma UFVJM"
    assert body["signed_at"] is not None

    # O hash impresso no PDF (o do CONTEÚDO) também verifica — é o que o QR carrega.
    content_hash = signed["content"]["content_sha256"]
    r2 = await client.get(f"{V2}/reports/{report_id}/verify", params={"hash": content_hash})
    assert r2.json()["valid"] is True

    storage.delete(signed["storage_key"])


async def test_verify_recusa_hash_errado(client, scenario):
    created = await client.post(
        f"{V2}/projects/{scenario['project_id']}/reports",
        json={"title": "Laudo verificável"},
        headers=scenario["signer_h"],
    )
    report_id = created.json()["id"]
    signed = (
        await client.post(f"{V2}/reports/{report_id}/sign", headers=scenario["signer_h"])
    ).json()

    r = await client.get(f"{V2}/reports/{report_id}/verify", params={"hash": "deadbeef" * 8})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    # Um laudo que não confere não vaza NADA sobre o laudo verdadeiro.
    assert body["code"] is None
    assert body["organization"] is None

    storage.delete(signed["storage_key"])


async def test_lista_laudos_do_projeto(client, scenario):
    for titulo in ("Laudo A", "Laudo B"):
        r = await client.post(
            f"{V2}/projects/{scenario['project_id']}/reports",
            json={"title": titulo},
            headers=scenario["signer_h"],
        )
        assert r.status_code == 201, r.text

    r = await client.get(
        f"{V2}/projects/{scenario['project_id']}/reports", headers=scenario["signer_h"]
    )
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_pdf_e_um_pdf_de_verdade():
    """O PDF sozinho, sem banco: bytes válidos e com o conteúdo dentro."""
    content = {
        "title": "Laudo de teste",
        "generated_at": "2026-07-13T10:00:00+00:00",
        "organization": {"name": "Laboratório Rizoma", "cnpj": "12.345.678/0001-90"},
        "project": {"code": "PRJ-1", "name": "INOVAHERB", "description": "Micobioma.",
                    "marker_type": "ITS"},
        "customer": {"name": "Fazenda X", "contact_email": "a@b.com"},
        "samples": [{"code": "AM-01", "matrix": "solo", "treatment_group": "controle",
                     "replicate": 1, "status": "received", "occurred_at": None}],
        "results": [{"sample_code": "AM-01", "analyte": "Cádmio", "unit": "mg/kg",
                     "lod": "0.05", "loq": "0.15", "uncertainty": "0.002",
                     "below_lod": True, "display_value": "<0.05", "value_numeric": "0.01"}],
        "bioinformatics": [{"analysis_type": "ancombc2", "summary": "12 táxons significativos"}],
        "signed_by_name": "Bruno Responsável Técnico",
        "signed_at": "2026-07-13T10:05:00+00:00",
        "content_sha256": "a" * 64,
    }
    pdf = build_report_pdf(content, "LAU-PRJ-1", 1, "http://x/api/v2/reports/1/verify?hash=aaa")

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000
