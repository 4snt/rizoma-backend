"""Contrato de módulo de laboratório — tcc-rizoma#8.

Isto é a INTERFACE, não o refactor. Define o que um módulo de domínio
(`microbioma-solo` hoje; `microbioma-clinico`, `biobanco`, `agua-alimentos`
amanhã, ver rascunho `07-analise-padroes-compatibilidade.md`) precisa
declarar pro núcleo genérico de LIMS (samples/projects/custody/reports)
conseguir tratá-lo sem `if matrix == 'solo'` espalhado pelo código.

Por que só a interface e não o refactor completo: hoje `samples.matrix` é um
CHECK constraint fixo no schema (ver `alembic/versions/0001_mvp_baseline.py`)
com os valores específicos de solo (`solo`, `raiz`, `biochar`, ...). Extrair
isso de verdade — tarefa da issue "Extrair entidades genéricas do módulo de
microbioma" — significa mexer no schema que `lims/repository.py` já usa em
produção, com risco real de quebrar INOVAHERB/Pós-Fogo/Biorremediação (a
própria issue #8 lista isso como critério de aceite). Não é troca segura pra
fazer às cegas numa sessão; fica documentado aqui como o próximo passo.

Migração recomendada (ordem, cada item é fatiável em issue própria):
  1. Este contrato (pronto).
  2. `LabModuleRegistry` — um dict slug -> LabModule, carregado no startup.
  3. Trocar o CHECK de `samples.matrix` por uma FK pra uma tabela
     `sample_matrices(module_slug, value)`, populada pelo registry no boot.
  4. Implementar `MicrobiomaSoloModule` com os valores que já existem hoje
     (migração é um no-op de dados — os valores continuam os mesmos).
  5. Só depois, plugins de fato novos (clínico, biobanco) viram possíveis
     sem tocar o núcleo.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class LabModuleMetadata:
    slug: str
    name: str
    # Valores válidos de `samples.matrix` para amostras deste módulo — hoje
    # isso é o CHECK constraint do banco; um módulo novo precisaria dessa
    # lista pra registrar os próprios valores sem tocar no schema genérico.
    sample_matrices: tuple[str, ...]


class SampleMetadataValidator(Protocol):
    """Cada módulo valida os metadados extras da própria amostra — o núcleo
    genérico só garante campos comuns (code, matrix, occurred_at, geo).
    Ex: microbioma-solo pode exigir profundidade de coleta; microbioma-clínico
    exigiria dado de paciente (sob outras regras de privacidade, LGPD/HIPAA).
    """

    def __call__(self, metadata: dict[str, Any]) -> None:
        """Levanta ValueError com mensagem de domínio se inválido."""
        ...


class LabModule(ABC):
    """Um módulo de domínio verticalizado sobre o núcleo genérico de LIMS.

    `microbioma-solo` (o único que existe hoje, implícito no código atual —
    ainda não extraído) seria o primeiro a implementar isto.
    """

    @abstractmethod
    def metadata(self) -> LabModuleMetadata: ...

    @abstractmethod
    def validate_sample_metadata(self, metadata: dict[str, Any]) -> None:
        """Levanta ValueError (vira 422 no service) se os metadados
        específicos do domínio (além dos campos genéricos de Sample) forem
        inválidos."""
        ...

    def report_template_name(self, analysis_type: str) -> str | None:
        """Nome do template de laudo pra este tipo de análise, se o módulo
        tiver um próprio. None = usa o template genérico do núcleo."""
        return None
