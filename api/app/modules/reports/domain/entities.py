"""Entidade Laudo (Report) e as duas funções de hash puras que a protegem.

Um laudo é um **snapshot**, não uma view: `content` congela o que era verdade
no momento da emissão. Dois hashes, dois propósitos:
  - `content_hash(content)` — hash do snapshot JSON, existe ANTES do PDF ser
    renderizado, por isso pode estar impresso nele e codificado no QR.
  - `Report.sha256` — hash do ARQUIVO PDF já renderizado, calculado depois.
    Não pode estar dentro do próprio PDF (imprimir o hash mudaria o hash).
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.reports.domain.exceptions import AlreadyPublishedError


def jsonable(value: Any) -> Any:
    """Snapshot precisa virar JSON puro: Decimal e datetime não são
    serializáveis. Decimal vira STRING, não float — 0.05 em float binário não
    é 0.05, e um laudo não pode perder precisão na serialização."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def content_hash(content: dict[str, Any]) -> str:
    """Hash canônico do snapshot: chaves ordenadas, sem o próprio campo de
    hash (senão o hash dependeria de si mesmo)."""
    payload = {k: v for k, v in content.items() if k != "content_sha256"}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class Report:
    id: UUID
    organization_id: UUID
    project_id: UUID
    code: str
    version: int
    title: str
    status: str = "draft"
    content: dict[str, Any] | None = None
    storage_key: str | None = None
    sha256: str | None = None
    signed_by: UUID | None = None
    signed_at: datetime | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None

    def assert_can_be_signed(self) -> None:
        if self.status == "published":
            raise AlreadyPublishedError(
                "Laudo já publicado. Um laudo assinado é imutável — emita uma versão nova."
            )

    def matches_hash(self, provided_hash: str) -> bool:
        """`/verify` aceita tanto o hash do conteúdo quanto o do arquivo —
        ambos identificam unicamente o mesmo laudo emitido."""
        accepted = {
            h for h in (self.sha256, (self.content or {}).get("content_sha256")) if h
        }
        return provided_hash.strip().lower() in {h.lower() for h in accepted}

    def to_dict(self, *, download_url: str | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "code": self.code,
            "version": self.version,
            "title": self.title,
            "status": self.status,
            "sha256": self.sha256,
            "storage_key": self.storage_key,
            "signed_by": self.signed_by,
            "signed_at": self.signed_at,
            "created_at": self.created_at,
            "content": self.content,
            "download_url": download_url,
        }

    def to_list_item(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "code": self.code,
            "version": self.version,
            "title": self.title,
            "status": self.status,
            "sha256": self.sha256,
            "signed_at": self.signed_at,
            "created_at": self.created_at,
        }
