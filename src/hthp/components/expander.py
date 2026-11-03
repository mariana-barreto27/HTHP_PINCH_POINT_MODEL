"""Equilibrium adiabatic expander, also permitting liquid/two-phase states.

This is a thermodynamic efficiency model, not a validated commercial or Tesla
turbine geometry. Zero isentropic efficiency is the throttling-valve limit.
"""

from dataclasses import dataclass
import math

from hthp.thermo.properties import props_si_cached
from hthp.thermo.state import ThermodynamicState


@dataclass(frozen=True)
class ExpanderResult:
    outlet: ThermodynamicState
    isentropic_outlet_enthalpy_kJ_kg: float
    specific_shaft_work_kJ_kg: float
    isentropic_efficiency: float
    pressure_ratio: float


@dataclass(frozen=True)
class AdiabaticExpander:
    isentropic_efficiency: float = 0.50

    def __post_init__(self) -> None:
        if not math.isfinite(self.isentropic_efficiency) or not (
            0.0 <= self.isentropic_efficiency <= 1.0
        ):
            raise ValueError("Expander isentropic efficiency must be in [0, 1].")

    def expand(self, refrigerant: str, inlet: ThermodynamicState,
               outlet_pressure_Pa: float) -> ExpanderResult:
        if not all(math.isfinite(value) for value in (
            inlet.pressure_Pa, inlet.enthalpy_kJ_kg,
            inlet.entropy_kJ_kgK, outlet_pressure_Pa,
        )) or not 0.0 < outlet_pressure_Pa < inlet.pressure_Pa:
            raise ValueError("The expander requires a finite positive pressure drop.")
        h_out_is = props_si_cached(
            "H", "P", outlet_pressure_Pa, "S",
            inlet.entropy_kJ_kgK * 1000.0, refrigerant,
        ) / 1000.0
        available = inlet.enthalpy_kJ_kg - h_out_is
        if not math.isfinite(available) or available < -1e-9:
            raise ValueError("No non-negative isentropic expansion work is available.")
        work = self.isentropic_efficiency * max(0.0, available)
        outlet = ThermodynamicState.from_pressure_enthalpy(
            refrigerant, outlet_pressure_Pa, inlet.enthalpy_kJ_kg - work,
        )
        return ExpanderResult(
            outlet=outlet, isentropic_outlet_enthalpy_kJ_kg=h_out_is,
            specific_shaft_work_kJ_kg=work,
            isentropic_efficiency=self.isentropic_efficiency,
            pressure_ratio=inlet.pressure_Pa / outlet_pressure_Pa,
        )
