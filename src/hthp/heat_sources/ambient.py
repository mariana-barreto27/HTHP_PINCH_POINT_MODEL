"""Fonte ambiente tratada como um reservatório térmico."""

from dataclasses import dataclass

from hthp.heat_sources.base import HeatSourceEvaluation


@dataclass(frozen=True)
class AmbientHeatSource:
    ambient_temperature_C: float = 25.0
    evaporator_approach_K: float = 5.0

    def __post_init__(self) -> None:
        if self.evaporator_approach_K <= 0.0:
            raise ValueError("A aproximação do evaporador deve ser positiva.")

    def evaporation_temperature_C(self) -> float:
        return self.ambient_temperature_C - self.evaporator_approach_K

    def evaluate(self, heat_extracted_kW: float) -> HeatSourceEvaluation:
        return HeatSourceEvaluation(
            name="Ambiente",
            evaporation_temperature_C=self.evaporation_temperature_C(),
            heat_extracted_kW=heat_extracted_kW,
            feasible=True,
        )

