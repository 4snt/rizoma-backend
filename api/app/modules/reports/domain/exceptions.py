"""Exceções de domínio de laudos — `service.py` traduz para HTTP."""


class NotFoundError(Exception):
    """Laudo não existe nesta organização."""


class AlreadyPublishedError(Exception):
    """Um laudo assinado é imutável — corrigir exige uma versão nova, não
    reassinar este."""
