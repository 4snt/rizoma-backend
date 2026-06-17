"""Testes unitários do SampleParser — parsing de nomes de FASTQ Illumina.

Cobre o formato real ({16S|ITS}-{placa}{numero}_{grupo}_L00x_R{1,2}_xxx.fastq.gz),
incluindo o caso ITS-B01 que era rejeitado antes da generalização da placa.
"""
import pytest

from app.domain.sample.services import SampleParser

parser = SampleParser()


@pytest.mark.parametrize(
    "filename,marker,sample,group,replicate,pair",
    [
        ("16S-A_01_T1B2_L001_R1_001.fastq.gz", "16S", "01", "T1B2", 2, "R1"),
        ("16S-A_02_T1B2_B_L001_R1_001.fastq.gz", "16S", "02", "T1B2_B", 2, "R1"),
        ("16S-A04_T2B1_L001_R1_001.fastq.gz", "16S", "04", "T2B1", 1, "R1"),
        ("ITS-B01_T1B2_L001_R1_001.fastq.gz", "ITS", "01", "T1B2", 2, "R1"),
        ("16S-A_05_T5B2_A_L001_R1_001.fastq.gz", "16S", "05", "T5B2_A", 2, "R1"),
        ("ITSA_02_T1B2_B_L001_R1_001.fastq.gz", "ITS", "02", "T1B2_B", 2, "R1"),
        ("16S-A_51_L001_R2_001.fastq.gz", "16S", "51", "S51", 51, "R2"),
    ],
)
def test_parse_valid_names(filename, marker, sample, group, replicate, pair):
    parsed = parser.parse(filename)
    assert parsed.marker_type == marker
    assert parsed.sample_number == sample
    assert parsed.treatment_group == group
    assert parsed.replicate == replicate
    assert parsed.read_pair == pair


def test_its_b01_regression():
    """Regressão: placa que não é 'A' (ITS-B01) deve ser aceita."""
    parsed = parser.parse("ITS-B01_T1B2_L001_R1_001.fastq.gz")
    assert parsed.marker_type == "ITS"
    assert parsed.read_pair == "R1"


def test_plain_fastq_extension():
    parsed = parser.parse("16S-A_01_T1B2_L001_R2_001.fastq")
    assert parsed.read_pair == "R2"


@pytest.mark.parametrize(
    "filename",
    [
        "amostra_qualquer.fastq.gz",
        "16S-A_01_T1B2_L001_R3_001.fastq.gz",   # par inválido (R3)
        "18S-A_01_T1B2_L001_R1_001.fastq.gz",   # marcador não suportado
        "16S-A_01_T1B2_L001_R1_001.txt",        # extensão errada
        "",
    ],
)
def test_parse_invalid_names_raise(filename):
    with pytest.raises(ValueError):
        parser.parse(filename)
