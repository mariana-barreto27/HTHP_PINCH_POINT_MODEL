"""Condensador com saída sub-resfriada."""

from dataclasses import dataclass

from hthp.thermo.properties import saturation_pressure_Pa
from hthp.thermo.state import ThermodynamicState


@dataclass(frozen=True)
class Condenser:
    condensation_temperature_C: float
    subcooling_K: float

    def outlet_state(self, refrigerant: str) -> ThermodynamicState:
        if self.subcooling_K < 0.0:
            raise ValueError("O sub-resfriamento não pode ser negativo.")
        pressure = saturation_pressure_Pa(
            refrigerant,
            self.condensation_temperature_C,
        )
        return ThermodynamicState.from_pressure_temperature(
            refrigerant,
            pressure,
            self.condensation_temperature_C - self.subcooling_K,
        )

