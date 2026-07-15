"""Exceções de domínio de laboratório — `service.py` traduz para HTTP."""


class NotFoundError(Exception):
    """Resultado (ou amostra referenciada) não existe nesta organização."""


class InvalidResultError(Exception):
    """Violação de invariante do resultado (ex.: sem valor, sem justificativa
    de correção)."""


class SegregationOfDutiesViolation(Exception):
    """Quem produziu o resultado tentou revisá-lo. ISO 17025 exige que sejam
    pessoas diferentes."""
