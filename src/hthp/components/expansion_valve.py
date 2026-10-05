"""Válvula de expansão isentálpica."""

from dataclasses import dataclass

from hthp.thermo.state import ThermodynamicState


@dataclass(frozen=True)
class ExpansionValve:
    def expand(
        self,
        refrigerant: str,
        inlet: ThermodynamicState,
        outlet_pressure_Pa: float,
    ) -> ThermodynamicState:
        if outlet_pressure_Pa >= inlet.pressure_Pa:
            raise ValueError("A válvula precisa reduzir a pressão.")
        return ThermodynamicState.from_pressure_enthalpy(
            refrigerant,
            outlet_pressure_Pa,
            inlet.enthalpy_kJ_kg,
        )

