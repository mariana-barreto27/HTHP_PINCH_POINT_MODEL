"""Fonte sensível de processo com capacidade térmica finita."""

from dataclasses import dataclass

from hthp.heat_sources.base import HeatSourceEvaluation


@dataclass(frozen=True)
class ProcessHeatSource:
    inlet_temperature_C: float
    mass_flow_kg_s: float
    specific_heat_kJ_kgK: float
    minimum_outlet_temperature_C: float
    evaporator_approach_K: float = 5.0

    def __post_init__(self) -> None:
        if self.mass_flow_kg_s <= 0.0:
            raise ValueError("A vazão da fonte de processo deve ser positiva.")
        if self.specific_heat_kJ_kgK <= 0.0:
            raise ValueError("O calor específico deve ser positivo.")
        if self.minimum_outlet_temperature_C >= self.inlet_temperature_C:
            raise ValueError(
                "A temperatura mínima de saída deve ser menor que a de entrada."
            )
        if self.evaporator_approach_K <= 0.0:
            raise ValueError("A aproximação do evaporador deve ser positiva.")

    def evaporation_temperature_C(self) -> float:
        return self.minimum_outlet_temperature_C - self.evaporator_approach_K

    @property
    def maximum_heat_kW(self) -> float:
        return (
            self.mass_flow_kg_s
            * self.specific_heat_kJ_kgK
            * (self.inlet_temperature_C - self.minimum_outlet_temperature_C)
        )

    def evaluate(self, heat_extracted_kW: float) -> HeatSourceEvaluation:
        outlet_temperature = self.inlet_temperature_C - heat_extracted_kW / (
            self.mass_flow_kg_s * self.specific_heat_kJ_kgK
        )
        feasible = heat_extracted_kW <= self.maximum_heat_kW + 1.0e-9
        return HeatSourceEvaluation(
            name="Calor de processo",
            evaporation_temperature_C=self.evaporation_temperature_C(),
            heat_extracted_kW=heat_extracted_kW,
            feasible=feasible,
            outlet_temperature_C=outlet_temperature,
            maximum_heat_kW=self.maximum_heat_kW,
        )

