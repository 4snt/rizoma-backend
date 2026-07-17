"""Object storage (boto3) — seleção de endpoint/credenciais e utilitários puros.

O ponto sensível é o `_client`: em dev fala com o MinIO (endpoint + chaves
explícitas); em produção AWS os dois ficam vazios e o boto3 resolve o endpoint
regional do S3 e pega a credencial da IAM role da task (ADR-001 / DEPLOY_AWS).
Este arquivo trava esse contrato sem rede e sem banco.
"""
import hashlib
import io

import pytest

from app.core.config import settings
from app.shared import storage


@pytest.fixture(autouse=True)
def _clear_client_cache():
    storage.internal_client.cache_clear()
    storage.public_client.cache_clear()
    yield
    storage.internal_client.cache_clear()
    storage.public_client.cache_clear()


def test_client_modo_minio_usa_endpoint_e_chaves(monkeypatch):
    monkeypatch.setattr(settings, "s3_access_key", "rizoma")
    monkeypatch.setattr(settings, "s3_secret_key", "rizoma123")

    c = storage._client("http://minio:9000")

    assert c.meta.endpoint_url == "http://minio:9000"
    creds = c._request_signer._credentials
    assert creds.access_key == "rizoma"
    assert creds.secret_key == "rizoma123"


def test_client_modo_aws_resolve_endpoint_regional_sem_chaves(monkeypatch):
    # Endpoint e chaves vazios: é o modo produção. O client tem de nascer sem
    # explodir (credencial é resolvida lazy, na hora da chamada) e apontar para
    # o endpoint regional nativo do S3.
    monkeypatch.setattr(settings, "s3_access_key", "")
    monkeypatch.setattr(settings, "s3_secret_key", "")
    monkeypatch.setattr(settings, "s3_region", "us-east-1")

    c = storage._client("")

    assert "amazonaws.com" in c.meta.endpoint_url


def test_build_key_prefixa_por_org_e_sanitiza_barra():
    key = storage.build_key("org1", "proj1", "samp1", "sub/dir/reads.fastq.gz")
    assert key == "org/org1/projects/proj1/samples/samp1/sub_dir_reads.fastq.gz"


def test_presign_upload_assina_com_host_publico(monkeypatch):
    monkeypatch.setattr(settings, "s3_access_key", "rizoma")
    monkeypatch.setattr(settings, "s3_secret_key", "rizoma123")
    monkeypatch.setattr(settings, "s3_public_endpoint", "http://localhost:9000")
    monkeypatch.setattr(settings, "s3_bucket", "rizoma")

    pu = storage.presign_upload(
        "org/x/reads.fastq.gz", content_type="application/gzip", max_bytes=1024
    )

    assert pu.storage_key == "org/x/reads.fastq.gz"
    assert "localhost:9000" in pu.url
    assert pu.fields["Content-Type"] == "application/gzip"
    # A policy carrega a restrição de tamanho e a chave assinadas.
    assert "policy" in pu.fields


def test_presign_download_devolve_url_assinada(monkeypatch):
    monkeypatch.setattr(settings, "s3_access_key", "rizoma")
    monkeypatch.setattr(settings, "s3_secret_key", "rizoma123")
    monkeypatch.setattr(settings, "s3_public_endpoint", "http://localhost:9000")
    monkeypatch.setattr(settings, "s3_bucket", "rizoma")

    url = storage.presign_download("org/x/reads.fastq.gz", expires=120)

    assert url.startswith("http://localhost:9000/")
    assert "X-Amz-Signature=" in url
    assert "X-Amz-Expires=120" in url


def test_sha256_stream_bate_com_hashlib():
    data = b"ACGT" * 4096
    got = storage.sha256_stream(io.BytesIO(data), chunk=1000)
    assert got == hashlib.sha256(data).hexdigest()
