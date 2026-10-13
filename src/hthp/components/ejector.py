"""Adiabatic two-phase ejector, constant-pressure mixing model.

Mateu-Royo et al. (2020), doi:10.1016/j.ijrefrig.2020.07.016,
equations (15)-(20). Inlet/outlet kinetic energies are neglected, NOT
the internal nozzle and mixing velocities. Enthalpies use kJ/kg here;
the factor 1000 is essential when converting them to velocities in m/s.
"""

from dataclasses import dataclass
import math

from hthp.thermo.properties import props_si_cached
from hthp.thermo.state import ThermodynamicState


@dataclass(frozen=True)
class EjectorResult:
    outlet: ThermodynamicState
    nozzle_outlet: ThermodynamicState
    mixing_state: ThermodynamicState
    entrainment_ratio: float
    nozzle_velocity_m_s: float
    mixing_velocity_m_s: float
    pressure_lift_ratio: float
    specific_energy_residual_kJ_kg: float


@dataclass(frozen=True)
class TwoPhaseEjector:
    nozzle_efficiency: float = 0.50
    mixing_efficiency: float = 0.50
    diffuser_efficiency: float = 0.50

    def __post_init__(self):
        for efficiency in (self.nozzle_efficiency, self.mixing_efficiency,
                           self.diffuser_efficiency):
            if not math.isfinite(efficiency) or not 0 < efficiency <= 1:
                raise ValueError("Ejector efficiencies must be in (0, 1].")

    def evaluate(self, refrigerant, primary, secondary, entrainment_ratio):
        """Evaluate a trial ratio; the CYCLE must close separator mass balance.

        As in Fig. 3, mixing pressure is the evaporator/secondary pressure.
        No arbitrary outlet-pressure or COP multiplier is prescribed.
        """
        mu = float(entrainment_ratio)
        if not math.isfinite(mu) or mu <= 0:
            raise ValueError("The ejector entrainment ratio must be positive.")
        pressure = secondary.pressure_Pa
        if primary.pressure_Pa <= pressure:
            raise ValueError("The motive stream must have higher pressure.")
        h_nozzle_is = props_si_cached(
            "H", "P", pressure, "S", primary.entropy_kJ_kgK * 1000,
            refrigerant) / 1000
        drop = primary.enthalpy_kJ_kg - h_nozzle_is
        if drop <= 0:
            raise ValueError("No positive nozzle expansion work is available.")
        velocity = math.sqrt(2000 * self.nozzle_efficiency * drop)
        mixed_velocity = velocity * math.sqrt(self.mixing_efficiency) / (1 + mu)
        outlet_h = (primary.enthalpy_kJ_kg + mu * secondary.enthalpy_kJ_kg) / (1 + mu)
        mixing_h = outlet_h - mixed_velocity**2 / 2000
        mixing = ThermodynamicState.from_pressure_enthalpy(
            refrigerant, pressure, mixing_h)
        diffuser_is_h = mixing_h + self.diffuser_efficiency * (outlet_h - mixing_h)
        outlet_pressure = props_si_cached(
            "P", "H", diffuser_is_h * 1000, "S",
            mixing.entropy_kJ_kgK * 1000, refrigerant)
        if not pressure < outlet_pressure < primary.pressure_Pa:
            raise ValueError("Ejector pressure recovery is outside physical limits.")
        outlet = ThermodynamicState.from_pressure_enthalpy(
            refrigerant, outlet_pressure, outlet_h)
        nozzle = ThermodynamicState.from_pressure_enthalpy(
            refrigerant, pressure, primary.enthalpy_kJ_kg - velocity**2 / 2000)
        return EjectorResult(
            outlet=outlet, nozzle_outlet=nozzle, mixing_state=mixing,
            entrainment_ratio=mu, nozzle_velocity_m_s=velocity,
            mixing_velocity_m_s=mixed_velocity,
            pressure_lift_ratio=outlet_pressure / pressure,
            specific_energy_residual_kJ_kg=(
                (1 + mu) * outlet_h - primary.enthalpy_kJ_kg
                - mu * secondary.enthalpy_kJ_kg),
        )
