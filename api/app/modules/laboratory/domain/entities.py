"""Entidades do domínio de laboratório: Resultado e suas Versões.

Um `LabResult` é o cabeçalho fixo (amostra, analito, método); `ResultVersion`
é cada medição/correção/revisão, append-only. Nunca há `UPDATE` em versão —
correção e revisão são sempre uma versão nova, fabricada a partir da anterior
pelos métodos `corrected()`/`reviewed()`.
"""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.laboratory.domain.exceptions import (
    InvalidResultError,
    SegregationOfDutiesViolation,
)


def _is_below_lod(value_numeric: Decimal | None, lod: Decimal | None) -> bool:
    return value_numeric is not None and lod is not None and value_numeric < lod


@dataclass
class ResultVersion:
    id: UUID
    organization_id: UUID
    result_id: UUID
    version: int
    value_numeric: Decimal | None
    value_text: str | None
    unit: str
    lod: Decimal | None = None
    loq: Decimal | None = None
    uncertainty: Decimal | None = None
    below_lod: bool = False
    status: str = "submitted"
    supersedes: UUID | None = None
    change_reason: str | None = None
    created_by: UUID | None = None
    reviewed_by: UUID | None = None
    created_at: datetime | None = None

    @property
    def display_value(self) -> str:
        """Como o resultado deve ser LIDO por um humano.

        Abaixo do limite de detecção, o resultado não é "0" e não é
        "desconhecido": é "<LOD". Imprimir 0 afirma ausência que o método não
        mediu; imprimir null esconde uma medição que aconteceu. Ambos
        falsificam o laudo.
        """
        if self.below_lod and self.lod is not None:
            return f"<{self.lod}"
        if self.value_numeric is not None:
            return str(self.value_numeric)
        return self.value_text or ""

    @classmethod
    def first(
        cls,
        *,
        id: UUID,
        organization_id: UUID,
        result_id: UUID,
        value_numeric: Decimal | None,
        value_text: str | None,
        unit: str,
        lod: Decimal | None,
        loq: Decimal | None,
        uncertainty: Decimal | None,
        created_by: UUID,
    ) -> "ResultVersion":
        if value_numeric is None and not value_text:
            raise InvalidResultError(
                "Informe value_numeric ou value_text — um resultado sem valor "
                "não é um resultado."
            )
        return cls(
            id=id,
            organization_id=organization_id,
            result_id=result_id,
            version=1,
            value_numeric=value_numeric,
            value_text=value_text,
            unit=unit,
            lod=lod,
            loq=loq,
            uncertainty=uncertainty,
            below_lod=_is_below_lod(value_numeric, lod),
            status="submitted",
            created_by=created_by,
        )

    def corrected(
        self,
        *,
        id: UUID,
        value_numeric: Decimal | None,
        value_text: str | None,
        unit: str | None,
        lod: Decimal | None,
        loq: Decimal | None,
        uncertainty: Decimal | None,
        change_reason: str | None,
        created_by: UUID,
    ) -> "ResultVersion":
        """Versão N+1 apontando para esta (N). Esta continua intacta no banco.

        Campos não informados herdam o valor desta versão — corrigir a
        unidade não deve apagar o LOD.
        """
        if not change_reason or not change_reason.strip():
            raise InvalidResultError(
                "change_reason é obrigatório para corrigir um resultado: uma "
                "correção sem justificativa não explica nada a um auditor "
                "(ISO 17025)."
            )
        new_value_numeric = value_numeric if value_numeric is not None else self.value_numeric
        new_lod = lod if lod is not None else self.lod
        return ResultVersion(
            id=id,
            organization_id=self.organization_id,
            result_id=self.result_id,
            version=self.version + 1,
            value_numeric=new_value_numeric,
            value_text=value_text if value_text is not None else self.value_text,
            unit=unit or self.unit,
            lod=new_lod,
            loq=loq if loq is not None else self.loq,
            uncertainty=uncertainty if uncertainty is not None else self.uncertainty,
            below_lod=_is_below_lod(new_value_numeric, new_lod),
            status="submitted",
            supersedes=self.id,
            change_reason=change_reason,
            created_by=created_by,
        )

    def assert_can_be_reviewed_by(self, reviewer_id: UUID) -> None:
        """Segregação de funções: quem produziu o resultado não pode
        aprová-lo. Validado aqui para dar um erro com explicação; o CHECK
        `chk_segregation` no banco é a rede de segurança embaixo."""
        if self.created_by == reviewer_id:
            raise SegregationOfDutiesViolation(
                "Segregação de funções: quem produziu o resultado não pode aprová-lo."
            )

    def reviewed(
        self, *, id: UUID, reviewer_id: UUID, new_status: str, reason: str
    ) -> "ResultVersion":
        """Versão N+1 de aprovação/retratação — mesmo valor da anterior.

        A autoria (`created_by`) permanece a do produtor original, não do
        revisor: é o que dá sentido ao CHECK `reviewed_by <> created_by` no
        banco, e ao princípio de segregação de funções da ISO 17025.
        """
        return ResultVersion(
            id=id,
            organization_id=self.organization_id,
            result_id=self.result_id,
            version=self.version + 1,
            value_numeric=self.value_numeric,
            value_text=self.value_text,
            unit=self.unit,
            lod=self.lod,
            loq=self.loq,
            uncertainty=self.uncertainty,
            below_lod=self.below_lod,
            status=new_status,
            supersedes=self.id,
            change_reason=reason,
            created_by=self.created_by,
            reviewed_by=reviewer_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "value_numeric": self.value_numeric,
            "value_text": self.value_text,
            "unit": self.unit,
            "lod": self.lod,
            "loq": self.loq,
            "uncertainty": self.uncertainty,
            "below_lod": self.below_lod,
            "status": self.status,
            "supersedes": self.supersedes,
            "change_reason": self.change_reason,
            "created_by": self.created_by,
            "reviewed_by": self.reviewed_by,
            "created_at": self.created_at,
            "display_value": self.display_value,
        }


@dataclass
class LabResult:
    """Agregado Resultado: o cabeçalho + todas as suas versões, em ordem."""

    id: UUID
    organization_id: UUID
    sample_id: UUID
    analyte: str
    method: str | None
    created_at: datetime | None
    versions: list[ResultVersion] = field(default_factory=list)

    @property
    def current(self) -> ResultVersion:
        """A versão corrente é a de maior número — nunca "a última editada",
        porque editar não existe aqui."""
        return self.versions[-1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sample_id": self.sample_id,
            "analyte": self.analyte,
            "method": self.method,
            "created_at": self.created_at,
            "current": self.current.to_dict(),
            "history": [v.to_dict() for v in self.versions],
        }
