"""Evaporador com saída superaquecida."""

from dataclasses import dataclass

from hthp.thermo.properties import saturation_pressure_Pa
from hthp.thermo.state import ThermodynamicState


@dataclass(frozen=True)
class Evaporator:
    evaporation_temperature_C: float
    superheat_K: float

    def outlet_state(self, refrigerant: str) -> ThermodynamicState:
        if self.superheat_K <= 0.0:
            raise ValueError("Use superaquecimento maior que zero na sucção.")
        pressure = saturation_pressure_Pa(
            refrigerant,
            self.evaporation_temperature_C,
            quality=1.0,
        )
        return ThermodynamicState.from_pressure_temperature(
            refrigerant,
            pressure,
            self.evaporation_temperature_C + self.superheat_K,
        )
