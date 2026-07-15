"""Exceções de domínio da fila de jobs — `service.py` traduz para HTTP."""


class NotFoundError(Exception):
    """Job não existe nesta organização."""


class JobRunningError(Exception):
    """Não há como matar o processo do worker a partir da API. Prometer que
    cancelou seria mentira."""


class NotCancellableError(Exception):
    """Job em estado que não aceita cancelamento (já terminou, por exemplo)."""
