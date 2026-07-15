"""Value Objects do domínio LIMS — só onde há invariante real a validar."""
from dataclasses import dataclass
from enum import Enum


class SampleStatus(str, Enum):
    """Espelha as chaves de `custody.TRANSICOES` — é a mesma máquina de estados,
    só que como tipo, para o resto do domínio referenciar em vez de usar string
    solta."""

    PLANNED = "planned"
    COLLECTED = "collected"
    IN_TRANSIT = "in_transit"
    RECEIVED = "received"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PROCESSING = "processing"
    ANALYZED = "analyzed"
    STORED = "stored"
    CONSUMED = "consumed"
    DISPOSED = "disposed"


@dataclass(frozen=True)
class GeoPoint:
    """Coordenada geográfica (WGS84).

    A validação de faixa aqui é a mesma que os schemas Pydantic já aplicam na
    borda da API (`ge=-90, le=90` etc.) — repetida de propósito: um `GeoPoint`
    só existe se for válido, não importa por onde entrar no domínio.
    """

    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not (-90 <= self.lat <= 90):
            raise ValueError(f"Latitude inválida: {self.lat}")
        if not (-180 <= self.lon <= 180):
            raise ValueError(f"Longitude inválida: {self.lon}")

    @classmethod
    def from_optional(cls, lat: float | None, lon: float | None) -> "GeoPoint | None":
        if lat is None or lon is None:
            return None
        return cls(lat=lat, lon=lon)
