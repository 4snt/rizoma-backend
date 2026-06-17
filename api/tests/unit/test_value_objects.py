"""Testes unitários dos value objects compartilhados."""
import pytest

from app.domain.shared.value_objects import MarkerType, ProjectCode


def test_marker_type_values():
    assert MarkerType.S16.value == "16S"
    assert MarkerType.ITS.value == "ITS"
    assert MarkerType("16S") is MarkerType.S16
    assert MarkerType("ITS") is MarkerType.ITS


def test_marker_type_invalid():
    with pytest.raises(ValueError):
        MarkerType("18S")


def test_project_code_is_str():
    code = ProjectCode("INOVAHERB")
    assert isinstance(code, str)
    assert str(code) == "INOVAHERB"
