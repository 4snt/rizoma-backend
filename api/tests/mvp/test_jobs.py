"""Fila de jobs — dequeue atômico, retry com backoff, reaper e isolamento.

Tudo contra o Postgres real: FOR UPDATE SKIP LOCKED e RLS não existem em mock.
"""
from datetime import datetime, timezone

from app.core.config import settings
import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text

from app.core.security import create_access_token
from app.modules.jobs import service as jobs_service
from app.modules.jobs.reaper import reap_orphan_jobs
from app.modules.jobs.router import router as jobs_router
from app.shared.ids import new_id

from .conftest import make_member, make_org, make_user

BASE = "/api/v2/jobs"
WORKER_HEADERS = {"X-Worker-Token": settings.worker_token}


@pytest_asyncio.fixture(autouse=True)
async def _clean_queue(sys_engine):
    """A fila é GLOBAL (o worker é cross-org). Um job pendurado de uma execução
    anterior seria pescado pelo dequeue deste teste. Limpa antes de cada um.

    E descarta o engine de sistema no fim: ele prende conexões ao event loop
    deste teste, e o próximo roda em outro loop."""
    async with jobs_service.system_sessionmaker()() as s:
        async with s.begin():
            await s.execute(
                text(
                    "DELETE FROM pipeline_jobs "
                    "WHERE status IN ('queued','running','retry_scheduled')"
                )
            )
    yield
    await jobs_service.dispose_system_engine()


@pytest_asyncio.fixture
async def app_client():
    app = FastAPI()
    app.include_router(jobs_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _make_project(db, org_id, user_id):
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
    return project_id


async def _make_org_scenario(db, role: str = "org_admin"):
    org_id = await make_org(db)
    user_id = await make_user(db)
    await make_member(db, org_id, user_id, role)
    project_id = await _make_project(db, org_id, user_id)
    token = create_access_token(str(user_id), role)
    return {
        "org_id": org_id,
        "user_id": user_id,
        "project_id": project_id,
        "headers": {"Authorization": f"Bearer {token}", "X-Organization": str(org_id)},
    }


@pytest_asyncio.fixture
async def scenario(db):
    yield await _make_org_scenario(db)


async def _enqueue(app_client, scenario, job_type="dada2", priority=100):
    r = await app_client.post(
        f"{BASE}/enqueue",
        json={
            "project_id": str(scenario["project_id"]),
            "job_type": job_type,
            "payload": {"marker": "ITS"},
            "priority": priority,
        },
        headers=scenario["headers"],
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_ciclo_completo_enqueue_dequeue_heartbeat_complete(app_client, scenario, db):
    job = await _enqueue(app_client, scenario)
    assert job["status"] == "queued"
    assert job["payload"] == {"marker": "ITS"}

    r = await app_client.post(
        f"{BASE}/worker/dequeue", json={"worker_id": "w-1"}, headers=WORKER_HEADERS
    )
    assert r.status_code == 200, r.text
    dq = r.json()
    assert dq["id"] == job["id"]
    assert dq["status"] == "running"
    assert dq["attempts"] == 1
    assert dq["worker_id"] == "w-1"
    # O worker recebe as URLs internas dos arquivos de entrada (nenhum aqui).
    assert dq["payload"]["input_files"] == []

    r = await app_client.post(
        f"{BASE}/worker/{job['id']}/heartbeat",
        json={"progress_pct": 42, "progress_stage": "denoise"},
        headers=WORKER_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["progress_pct"] == 42
    assert r.json()["progress_stage"] == "denoise"

    r = await app_client.post(
        f"{BASE}/worker/{job['id']}/complete",
        json={"analysis_type": "ancombc2", "result_data": {"taxa": ["Fusarium"], "n": 1}},
        headers=WORKER_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    assert r.json()["finished_at"] is not None

    r = await app_client.get(f"{BASE}/{job['id']}", headers=scenario["headers"])
    assert r.status_code == 200
    detail = r.json()
    assert detail["status"] == "completed"
    assert len(detail["results"]) == 1
    assert detail["results"][0]["analysis_type"] == "ancombc2"
    assert detail["results"][0]["result_data"] == {"taxa": ["Fusarium"], "n": 1}


async def test_worker_sem_token_e_401(app_client, scenario):
    await _enqueue(app_client, scenario)
    r = await app_client.post(f"{BASE}/worker/dequeue", json={"worker_id": "w-1"})
    assert r.status_code == 401


async def test_dequeue_inclui_urls_internas_dos_arquivos(app_client, scenario, db):
    """É assim que o worker lê o FASTQ: URL assinada, não bytes no banco."""
    async with db() as s:
        async with s.begin():
            await s.execute(
                text(
                    "INSERT INTO files (id, organization_id, project_id, category, "
                    "original_name, storage_key, upload_status) "
                    "VALUES (:i, :o, :p, 'fastq_r1', 'a_R1.fastq', :k, 'uploaded')"
                ),
                {
                    "i": str(new_id()),
                    "o": str(scenario["org_id"]),
                    "p": str(scenario["project_id"]),
                    "k": f"org/{scenario['org_id']}/x/a_R1.fastq",
                },
            )
    await _enqueue(app_client, scenario)

    r = await app_client.post(
        f"{BASE}/worker/dequeue", json={"worker_id": "w-1"}, headers=WORKER_HEADERS
    )
    assert r.status_code == 200
    files = r.json()["payload"]["input_files"]
    assert len(files) == 1
    assert files[0]["category"] == "fastq_r1"
    assert "X-Amz-Signature" in files[0]["url"]


async def test_fail_agenda_retry_com_backoff(app_client, scenario):
    job = await _enqueue(app_client, scenario)
    await app_client.post(
        f"{BASE}/worker/dequeue", json={"worker_id": "w-1"}, headers=WORKER_HEADERS
    )

    r = await app_client.post(
        f"{BASE}/worker/{job['id']}/fail",
        json={"error_code": "R_ERROR", "error_message": "phyloseq object vazio"},
        headers=WORKER_HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "retry_scheduled"
    assert body["attempts"] == 1
    next_retry = datetime.fromisoformat(body["next_retry_at"])
    assert next_retry > datetime.now(timezone.utc)
    assert body["error_code"] == "R_ERROR"


async def test_fail_repetido_vira_dead_letter(app_client, scenario, db):
    job = await _enqueue(app_client, scenario)

    for attempt in range(1, 4):
        r = await app_client.post(
            f"{BASE}/worker/dequeue", json={"worker_id": "w-1"}, headers=WORKER_HEADERS
        )
        assert r.status_code == 200, f"tentativa {attempt}: {r.text}"
        assert r.json()["attempts"] == attempt

        r = await app_client.post(
            f"{BASE}/worker/{job['id']}/fail",
            json={"error_message": "boom"},
            headers=WORKER_HEADERS,
        )
        assert r.status_code == 200
        esperado = "retry_scheduled" if attempt < 3 else "dead_letter"
        assert r.json()["status"] == esperado

        if attempt < 3:
            # O backoff empurra next_retry_at para o futuro; sem isto o próximo
            # dequeue não veria o job. Puxamos o relógio para trás.
            async with db() as s:
                async with s.begin():
                    await s.execute(
                        text("UPDATE pipeline_jobs SET next_retry_at = now() - interval '1 minute' "
                             "WHERE id = :i"),
                        {"i": job["id"]},
                    )

    # dead_letter sai da fila para sempre
    r = await app_client.post(
        f"{BASE}/worker/dequeue", json={"worker_id": "w-1"}, headers=WORKER_HEADERS
    )
    assert r.status_code == 204


async def test_cancel_de_queued_ok_e_de_running_409(app_client, scenario):
    job = await _enqueue(app_client, scenario)
    r = await app_client.post(f"{BASE}/{job['id']}/cancel", headers=scenario["headers"])
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    outro = await _enqueue(app_client, scenario)
    await app_client.post(
        f"{BASE}/worker/dequeue", json={"worker_id": "w-1"}, headers=WORKER_HEADERS
    )
    r = await app_client.post(f"{BASE}/{outro['id']}/cancel", headers=scenario["headers"])
    assert r.status_code == 409


async def test_reaper_devolve_job_orfao_para_a_fila(app_client, scenario, db):
    """Worker morto no meio de um SpiecEasi de 20 min. Sem o reaper, o job fica
    'running' até o fim dos tempos."""
    job = await _enqueue(app_client, scenario)
    await app_client.post(
        f"{BASE}/worker/dequeue", json={"worker_id": "w-morto"}, headers=WORKER_HEADERS
    )

    async with db() as s:
        async with s.begin():
            await s.execute(
                text(
                    "UPDATE pipeline_jobs SET heartbeat_at = now() - interval '2 hours' "
                    "WHERE id = :i"
                ),
                {"i": job["id"]},
            )

    stats = await reap_orphan_jobs()
    assert stats["requeued"] == 1

    async with db() as s:
        row = (
            await s.execute(
                text("SELECT status, worker_id FROM pipeline_jobs WHERE id = :i"),
                {"i": job["id"]},
            )
        ).mappings().one()
    assert row["status"] == "queued"
    assert row["worker_id"] is None

    # e volta a ser pescável
    r = await app_client.post(
        f"{BASE}/worker/dequeue", json={"worker_id": "w-2"}, headers=WORKER_HEADERS
    )
    assert r.status_code == 200
    assert r.json()["id"] == job["id"]


async def test_reaper_manda_para_dead_letter_quando_esgota_tentativas(app_client, scenario, db):
    job = await _enqueue(app_client, scenario)
    await app_client.post(
        f"{BASE}/worker/dequeue", json={"worker_id": "w-morto"}, headers=WORKER_HEADERS
    )
    async with db() as s:
        async with s.begin():
            await s.execute(
                text(
                    "UPDATE pipeline_jobs SET heartbeat_at = now() - interval '2 hours', "
                    "attempts = max_attempts WHERE id = :i"
                ),
                {"i": job["id"]},
            )

    stats = await reap_orphan_jobs()
    assert stats["dead_lettered"] == 1

    async with db() as s:
        st = (
            await s.execute(
                text("SELECT status FROM pipeline_jobs WHERE id = :i"), {"i": job["id"]}
            )
        ).scalar_one()
    assert st == "dead_letter"


async def test_isolamento_org_a_nao_ve_job_da_org_b(app_client, db):
    """A RLS é a segunda camada. Mesmo que o handler esqueça um WHERE, o banco
    não entrega a linha da outra organização."""
    a = await _make_org_scenario(db)
    b = await _make_org_scenario(db)

    job_b = await _enqueue(app_client, b)

    r = await app_client.get(f"{BASE}/", headers=a["headers"])
    assert r.status_code == 200
    assert job_b["id"] not in [j["id"] for j in r.json()]

    # acesso direto pelo id: 404, não 403 — a existência do job também é sigilo.
    r = await app_client.get(f"{BASE}/{job_b['id']}", headers=a["headers"])
    assert r.status_code == 404

    r = await app_client.get(f"{BASE}/", headers=b["headers"])
    assert [j["id"] for j in r.json()] == [job_b["id"]]
