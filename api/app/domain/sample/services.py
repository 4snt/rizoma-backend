import re
from dataclasses import dataclass, field


@dataclass
class ParsedSampleName:
    marker_type: str    # '16S' ou 'ITS'
    sample_number: str  # '01', '51', etc.
    treatment_group: str  # 'T1B2', 'T5B2_A', 'S51' para controles sem grupo
    replicate: int
    read_pair: str      # 'R1' ou 'R2'


class SampleParser:
    """
    Suporta o formato Illumina real dos arquivos de sequenciamento:

      {16S|ITS}[-]{placa}[_]{número}[_{T\\d+B\\d+[_letra]}]_L{lane}_R{1|2}_{idx}.fastq[.gz]

    A "placa" é qualquer letra (A, B, C…), não apenas A.

    Variantes presentes nos dados:
      16S-A_01_T1B2_L001_R1_001.fastq.gz       → padrão
      16S-A_02_T1B2_B_L001_R1_001.fastq.gz     → grupo com sub-réplica _B
      16S-A04_T2B1_L001_R1_001.fastq.gz         → sem underscore entre placa e número
      ITS-B01_T1B2_L001_R1_001.fastq.gz         → placa B (não apenas A)
      16S-A_05_T5B2_A_L001_R1_001.fastq.gz     → sub-réplica _A
      ITSA_02_T1B2_B_L001_R1_001.fastq.gz       → sem hífen (ITSA)
      16S-A_51_L001_R1_001.fastq.gz             → sem grupo de tratamento (controle)
    """

    _PATTERN = re.compile(
        r'^(?P<marker>16S|ITS)-?(?P<plate>[A-Z])_?'  # 16S-A_, ITS-B, ITSA_ — placa = qualquer letra
        r'(?P<sample>\d+)'                            # número da amostra
        r'(?:_(?P<group>T\d+B\d+(?:_[A-Z])?))?'      # grupo opcional: T1B2 ou T5B2_A
        r'_L\d+_R(?P<pair>[12])_\d+'                 # _L001_R1_001
        r'\.fastq(?:\.gz)?$',                         # .fastq ou .fastq.gz
        re.IGNORECASE,
    )

    def parse(self, filename: str) -> ParsedSampleName:
        m = self._PATTERN.match(filename)
        if not m:
            raise ValueError(
                f"Nome de arquivo não reconhecido: '{filename}'. "
                f"Formato esperado: 16S-A_01_T1B2_L001_R1_001.fastq.gz"
            )

        marker = m.group('marker').upper()
        sample = m.group('sample')
        group  = m.group('group')
        pair   = m.group('pair')

        if group:
            b = re.search(r'B(\d+)', group)
            replicate = int(b.group(1)) if b else int(sample)
        else:
            group = f'S{sample}'   # controle/branco sem grupo de tratamento
            replicate = int(sample)

        return ParsedSampleName(
            marker_type=marker,
            sample_number=sample,
            treatment_group=group,
            replicate=replicate,
            read_pair=f'R{pair}',
        )
