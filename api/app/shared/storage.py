"""Armazenamento de objetos (MinIO / S3) — ADR-001.

Substitui os PostgreSQL Large Objects. A regra que torna isso escalável:
**a API nunca toca o corpo do arquivo.** Ela só assina uma URL; os bytes vão
do browser direto para o MinIO. Um FASTQ de 8 GB nunca passa pela memória do
processo Python nem pelo WAL do Postgres.
"""
import hashlib
from dataclasses import dataclass
from functools import lru_cache

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.core.config import settings


@dataclass(frozen=True)
class PresignedUpload:
    url: str
    fields: dict
    storage_key: str


def _client(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=BotoConfig(signature_version="s3v4"),
    )


@lru_cache(maxsize=2)
def internal_client():
    """Client para operações servidor→MinIO (criar bucket, HEAD, delete)."""
    return _client(settings.s3_endpoint)


@lru_cache(maxsize=2)
def public_client():
    """Client usado só para ASSINAR. A assinatura precisa cobrir o host que o
    browser vai chamar — assinar com o host interno gera 403 no upload."""
    return _client(settings.s3_public_endpoint)


def ensure_bucket() -> None:
    c = internal_client()
    try:
        c.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        c.create_bucket(Bucket=settings.s3_bucket)


def build_key(org_id, project_id, sample_id, filename: str) -> str:
    """Chave prefixada por organização — facilita política de acesso e quota."""
    safe = filename.replace("/", "_").strip()
    return f"org/{org_id}/projects/{project_id}/samples/{sample_id}/{safe}"


def presign_upload(storage_key: str, content_type: str = "application/octet-stream",
                   max_bytes: int | None = None) -> PresignedUpload:
    """POST assinado. O browser envia o arquivo direto ao MinIO."""
    limit = max_bytes or settings.max_upload_size_mb * 1024 * 1024
    resp = public_client().generate_presigned_post(
        Bucket=settings.s3_bucket,
        Key=storage_key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 1, limit],
        ],
        ExpiresIn=settings.presign_expiry_seconds,
    )
    return PresignedUpload(url=resp["url"], fields=resp["fields"], storage_key=storage_key)


def presign_download(storage_key: str, expires: int | None = None) -> str:
    return public_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": storage_key},
        ExpiresIn=expires or settings.presign_expiry_seconds,
    )


def presign_download_internal(storage_key: str, expires: int | None = None) -> str:
    """URL assinada com o host interno — para o R Worker baixar de dentro da rede
    de containers. É assim que o worker lê o FASTQ sem que o arquivo precise
    morar no banco."""
    return internal_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": storage_key},
        ExpiresIn=expires or settings.presign_expiry_seconds,
    )


def head(storage_key: str) -> dict | None:
    """Confirma que o objeto existe de fato. Usado no /confirm: sem isso, o
    cliente poderia registrar metadados de um upload que nunca aconteceu."""
    try:
        r = internal_client().head_object(Bucket=settings.s3_bucket, Key=storage_key)
    except ClientError:
        return None
    return {"size_bytes": r["ContentLength"], "etag": r["ETag"].strip('"')}


def delete(storage_key: str) -> None:
    internal_client().delete_object(Bucket=settings.s3_bucket, Key=storage_key)


def sha256_stream(fileobj, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    while data := fileobj.read(chunk):
        h.update(data)
    return h.hexdigest()
