"""Misturador adiabático de correntes na mesma pressão."""

from dataclasses import dataclass
from typing import Sequence

from hthp.thermo.state import ThermodynamicState


@dataclass(frozen=True)
class Mixer:
    def mix(
        self,
        refrigerant: str,
        pressure_Pa: float,
        streams: Sequence[tuple[float, ThermodynamicState]],
    ) -> ThermodynamicState:
        if not streams:
            raise ValueError("O misturador precisa receber pelo menos uma corrente.")
        total_mass = sum(mass for mass, _ in streams)
        if total_mass <= 0.0:
            raise ValueError("A massa total no misturador deve ser positiva.")
        for mass, state in streams:
            if mass < 0.0:
                raise ValueError("Uma corrente não pode ter massa negativa.")
            relative_pressure_error = abs(state.pressure_Pa - pressure_Pa) / pressure_Pa
            if relative_pressure_error > 1.0e-7:
                raise ValueError("As correntes do misturador devem ter a mesma pressão.")

        mixed_enthalpy = sum(
            mass * state.enthalpy_kJ_kg for mass, state in streams
        ) / total_mass
        return ThermodynamicState.from_pressure_enthalpy(
            refrigerant,
            pressure_Pa,
            mixed_enthalpy,
        )

