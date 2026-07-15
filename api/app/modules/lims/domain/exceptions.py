"""Exceções de domínio do LIMS — o `service.py` (camada de aplicação) é quem
traduz estas para HTTP, não o repository."""


class DuplicateError(Exception):
    """Uma unicidade de negócio (nome de cliente, código de projeto/amostra
    dentro do escopo esperado) foi violada."""


class NotFoundError(Exception):
    """A entidade não existe — ou não existe *nesta organização*, o que dá no
    mesmo depois que a RLS filtra a linha."""
