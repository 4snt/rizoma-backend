"""Máquina de estados da amostra + cadeia de custódia com hash encadeado.

Duas ideias, uma responsabilidade cada:

1. TRANSICOES — o ciclo de vida legítimo de uma amostra. Não existe atalho:
   uma amostra não vai de 'planned' direto para 'analyzed' porque, na vida real,
   ela precisa ter sido coletada, transportada e recebida antes.

2. Hash chain — cada evento de custódia carrega o hash do anterior. Alterar um
   evento no meio da cadeia quebra todos os hashes a partir dali, e
   `verify_chain()` detecta. Combinado com o trigger append-only do banco
   (que RECUSA UPDATE/DELETE), a cadeia é prova de integridade — o requisito
   de rastreabilidade da ISO 17025.
"""
import hashlib
import json
from datetime import datetime
from typing import Any

# Estados do CHECK de `samples.status`. 'cancelled' não existe no schema — a
# amostra que não vira nada morre em 'disposed'.
TRANSICOES: dict[str, list[str]] = {
    "planned": ["collected"],
    "collected": ["in_transit"],
    "in_transit": ["received"],
    "received": ["accepted", "rejected"],
    "accepted": ["processing", "stored"],
    "rejected": ["disposed"],
    "processing": ["analyzed", "consumed"],
    "analyzed": ["stored", "disposed"],
    "stored": ["processing", "disposed"],
    "consumed": [],
    "disposed": [],
}

# Estado de destino → tipo de evento de custódia gravado.
# Um estado é o "onde a amostra está"; o evento é o "o que aconteceu com ela".
STATUS_TO_EVENT: dict[str, str] = {
    "collected": "coleta",
    "in_transit": "transporte",
    "received": "recebimento",
    "accepted": "transferencia",
    "rejected": "transferencia",
    "processing": "processamento",
    "analyzed": "processamento",
    "stored": "armazenamento",
    "consumed": "processamento",
    "disposed": "descarte",
}


class InvalidTransition(Exception):
    """Transição de estado que a máquina não permite."""

    def __init__(self, current: str, target: str) -> None:
        permitidos = TRANSICOES.get(current, [])
        alvo = ", ".join(permitidos) if permitidos else "nenhum (estado terminal)"
        super().__init__(
            f"Transição inválida: '{current}' → '{target}'. "
            f"A partir de '{current}' só é possível ir para: {alvo}."
        )
        self.current = current
        self.target = target


def can_transition(current: str, target: str) -> bool:
    return target in TRANSICOES.get(current, [])


def assert_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(current, target)


def event_type_for(target_status: str) -> str:
    return STATUS_TO_EVENT[target_status]


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def compute_hash(
    *,
    prev_hash: str | None,
    sample_id: Any,
    seq: int,
    event_type: str,
    occurred_at: Any,
    from_custodian: Any = None,
    to_custodian: Any = None,
) -> str:
    """SHA-256 de uma serialização canônica e determinística do evento.

    Canônica = chaves ordenadas, separadores fixos, datas em ISO-8601, UUIDs em
    texto. Se dois processos serializarem o mesmo evento, o byte é o mesmo — sem
    isso, `verify_chain()` acusaria adulteração em cadeias íntegras.
    """
    payload = {
        "prev_hash": prev_hash,
        "sample_id": str(sample_id),
        "seq": seq,
        "event_type": event_type,
        "occurred_at": _iso(occurred_at),
        "from_custodian": _iso(from_custodian),
        "to_custodian": _iso(to_custodian),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_chain(events: list[dict[str, Any]]) -> bool:
    """Recalcula a cadeia inteira do zero e compara com o que está gravado.

    `events` precisa vir ordenado por seq. Retorna False se qualquer hash,
    encadeamento ou numeração de seq divergir.
    """
    prev: str | None = None
    for i, ev in enumerate(events, start=1):
        if ev["seq"] != i:
            return False
        if ev["prev_hash"] != prev:
            return False
        expected = compute_hash(
            prev_hash=prev,
            sample_id=ev["sample_id"],
            seq=ev["seq"],
            event_type=ev["event_type"],
            occurred_at=ev["occurred_at"],
            from_custodian=ev.get("from_custodian"),
            to_custodian=ev.get("to_custodian"),
        )
        if expected != ev["hash"]:
            return False
        prev = ev["hash"]
    return True
