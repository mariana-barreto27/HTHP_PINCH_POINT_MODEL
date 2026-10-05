"""Corrente-fonte com temperatura de saída e pinch explícitos."""

from dataclasses import dataclass

from hthp.heat_sources.base import HeatSourceEvaluation
from hthp.thermo.properties import props_si_cached, to_kelvin


@dataclass(frozen=True)
class PinchStreamHeatSource:
    inlet_temperature_C: float = 20.0
    outlet_temperature_C: float = 10.0
    evaporator_pinch_K: float = 10.0
    pressure_bar: float = 1.0
    fluid: str = "Air"

    def __post_init__(self) -> None:
        if self.outlet_temperature_C >= self.inlet_temperature_C:
            raise ValueError("A fonte deve sair mais fria do evaporador.")
        if self.evaporator_pinch_K <= 0.0 or self.pressure_bar <= 0.0:
            raise ValueError("O pinch e a pressão da fonte devem ser positivos.")

    def evaporation_temperature_C(self) -> float:
        return self.outlet_temperature_C - self.evaporator_pinch_K

    def specific_enthalpy_drop_kJ_kg(self) -> float:
        pressure_Pa = self.pressure_bar * 1.0e5
        inlet_enthalpy = props_si_cached(
            "H",
            "P",
            pressure_Pa,
            "T",
            to_kelvin(self.inlet_temperature_C),
            self.fluid,
        ) / 1000.0
        outlet_enthalpy = props_si_cached(
            "H",
            "P",
            pressure_Pa,
            "T",
            to_kelvin(self.outlet_temperature_C),
            self.fluid,
        ) / 1000.0
        enthalpy_drop = inlet_enthalpy - outlet_enthalpy
        if enthalpy_drop <= 0.0:
            raise ValueError("A queda de entalpia da fonte deve ser positiva.")
        return enthalpy_drop

    def mass_flow_for_heat_kg_s(self, heat_extracted_kW: float) -> float:
        if heat_extracted_kW <= 0.0:
            raise ValueError("O calor retirado da fonte deve ser positivo.")
        return heat_extracted_kW / self.specific_enthalpy_drop_kJ_kg()

    def evaluate(self, heat_extracted_kW: float) -> HeatSourceEvaluation:
        return HeatSourceEvaluation(
            name="Corrente com pinch",
            evaporation_temperature_C=self.evaporation_temperature_C(),
            heat_extracted_kW=heat_extracted_kW,
            feasible=True,
            outlet_temperature_C=self.outlet_temperature_C,
        )
