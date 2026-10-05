"""Contrato comum para fontes de calor ambiente e de processo."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class HeatSourceEvaluation:
    name: str
    evaporation_temperature_C: float
    heat_extracted_kW: float
    feasible: bool
    outlet_temperature_C: float | None = None
    maximum_heat_kW: float | None = None


class HeatSource(Protocol):
    def evaporation_temperature_C(self) -> float:
        """Retorna a temperatura de saturação adotada no evaporador."""

    def evaluate(self, heat_extracted_kW: float) -> HeatSourceEvaluation:
        """Verifica a fonte após conhecer a carga térmica do evaporador."""

