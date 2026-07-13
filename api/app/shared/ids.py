"""Geração de identificadores.

UUIDv7 (não v4, não serial) porque o tablet em campo precisa gerar o ID da
amostra sem rede. O prefixo temporal mantém o índice B-tree ordenado, o que
UUIDv4 não faz.
"""
from uuid import UUID

from uuid_extensions import uuid7


def new_id() -> UUID:
    return uuid7()


def is_uuid7(value: UUID) -> bool:
    return value.version == 7
