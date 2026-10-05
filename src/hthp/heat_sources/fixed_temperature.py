"""Fonte interna com temperatura de evaporação prescrita."""

from dataclasses import dataclass

from hthp.heat_sources.base import HeatSourceEvaluation


@dataclass(frozen=True)
class FixedTemperatureHeatSource:
    temperature_C: float
    name: str = "Trocador de calor da cascata"

    def evaporation_temperature_C(self) -> float:
        return self.temperature_C

    def evaluate(self, heat_extracted_kW: float) -> HeatSourceEvaluation:
        return HeatSourceEvaluation(
            name=self.name,
            evaporation_temperature_C=self.temperature_C,
            heat_extracted_kW=heat_extracted_kW,
            feasible=True,
        )

