"""Ejector expansion cycle with a separator and a liquid/suction IHX.

Flow: compressor -> condenser -> optional WATER subcooler -> IHX hot side
-> motive nozzle -> separator. Separator vapour -> IHX cold side -> compressor;
separator liquid -> valve -> evaporator -> ejector secondary inlet.

The optional expander replaces ONLY that last liquid valve, from separator
pressure to evaporation pressure. It does not replace the motive nozzle or
recover the same pressure potential twice. Recovered work assists the motor
shaft; unrecovered expander power is an external loss, not useful heating.

The two mass streams are not injection streams. With mu=m_evap/m_compressor,
separator outlet quality must be x=1/(1+mu). Separator pressure and mu are
solved simultaneously with scipy.optimize.least_squares. IHX duty is set by
the prescribed compressor-inlet superheat, not a freely optimized effectiveness.
"""

from dataclasses import dataclass
import math

import numpy as np
from scipy.optimize import least_squares

from hthp.components.compressor import Compressor
from hthp.components.compressor_performance import IsentropicEfficiencyModel
from hthp.components.ejector import TwoPhaseEjector, EjectorResult
from hthp.components.evaporator import Evaporator
from hthp.components.expansion_valve import ExpansionValve
from hthp.components.expander import AdiabaticExpander, ExpanderResult
from hthp.heat_sources.base import HeatSource, HeatSourceEvaluation
from hthp.thermo.properties import critical_temperature_C, saturation_pressure_Pa
from hthp.thermo.state import ThermodynamicState


@dataclass(frozen=True)
class EjectorCycleConfig:
    refrigerant: str
    heat_source: HeatSource
    condensation_temperature_C: float
    heating_capacity_kW: float
    superheat_K: float = 5.0  # Evaporator outlet; also the IHX suction target.
    subcooling_K: float = 5.0  # Existing condenser outlet setting, unchanged.
    compressor_isentropic_efficiency: float = 0.70
    motor_efficiency: float = 0.95
    compressor_efficiency_model: IsentropicEfficiencyModel | None = None
    external_subcooling_specific_heat_kJ_kg: float = 0.0
    nozzle_efficiency: float = 0.50
    mixing_efficiency: float = 0.50
    diffuser_efficiency: float = 0.50
    ihx_minimum_approach_K: float = 5.0
    use_expander: bool = False
    expander_isentropic_efficiency: float = 0.50
    expander_recovery_efficiency: float = 1.0


@dataclass(frozen=True)
class EjectorCycleResult:
    config: EjectorCycleConfig
    evaporation_temperature_C: float
    states: dict[str, ThermodynamicState]
    ejector: EjectorResult
    separator_pressure_bar: float
    evaporator_pressure_bar: float
    entrainment_ratio: float
    separator_vapor_quality: float
    refrigerant_mass_flow_kg_s: float  # Compressor/condenser/motive stream.
    evaporator_mass_flow_kg_s: float
    evaporator_heat_kW: float
    condenser_heat_kW: float
    external_subcooler_heat_kW: float
    ihx_heat_kW: float
    ihx_minimum_approach_K: float
    compressor_shaft_power_kW: float
    compressor_electrical_power_kW: float
    compressor_isentropic_efficiency: float
    pressure_ratio: float
    heating_COP: float
    energy_balance_error_kW: float
    separator_mass_balance_error_kg_s: float
    ihx_balance_error_kW: float
    closure_residual: float
    heat_source: HeatSourceEvaluation
    expander_shaft_power_kW: float = 0.0
    recovered_power_kW: float = 0.0
    unrecovered_expander_power_kW: float = 0.0
    net_shaft_power_kW: float = 0.0
    net_electrical_power_kW: float = 0.0
    system_energy_balance_error_kW: float = 0.0
    expander: ExpanderResult | None = None


class EjectorCycle:
    def __init__(self, config):
        self.config = config

    def solve(self):
        c = self.config
        fluid = c.refrigerant
        expander_model = AdiabaticExpander(c.expander_isentropic_efficiency)
        if (not math.isfinite(c.expander_recovery_efficiency)
                or not 0 <= c.expander_recovery_efficiency <= 1):
            raise ValueError("Expander recovery efficiency must be in [0, 1].")
        tev = c.heat_source.evaporation_temperature_C()
        if not (math.isfinite(c.heating_capacity_kW) and c.heating_capacity_kW > 0
                and 0 < c.superheat_K and 0 <= c.subcooling_K
                and 0 <= c.external_subcooling_specific_heat_kJ_kg
                and 0 < c.ihx_minimum_approach_K
                and tev < c.condensation_temperature_C < critical_temperature_C(fluid)):
            raise ValueError("Invalid ejector-cycle temperatures, duty or IHX settings.")
        secondary = Evaporator(tev, c.superheat_K).outlet_state(fluid)
        pev = secondary.pressure_Pa
        pcd = saturation_pressure_Pa(fluid, c.condensation_temperature_C)
        if c.subcooling_K == 0:
            condenser = ThermodynamicState.from_pressure_quality(fluid, pcd, 0)
        else:
            condenser = ThermodynamicState.from_pressure_temperature(
                fluid, pcd, c.condensation_temperature_C - c.subcooling_K)
        water_sc = ThermodynamicState.from_pressure_enthalpy(
            fluid, pcd, condenser.enthalpy_kJ_kg
            - c.external_subcooling_specific_heat_kJ_kg)
        if water_sc.quality is not None and water_sc.quality > 0:
            raise ValueError("The IHX hot inlet must be liquid.")
        maximum_separator_temperature = (water_sc.temperature_C - c.superheat_K
                                         - c.ihx_minimum_approach_K)
        if maximum_separator_temperature <= tev + 1e-6:
            raise ValueError("No temperature head for the IHX and suction superheat.")
        pmax = min(pcd * (1 - 1e-8), saturation_pressure_Pa(
            fluid, maximum_separator_temperature, quality=1))
        if pmax <= pev * (1 + 1e-7):
            raise ValueError("No feasible separator pressure above evaporation.")
        ejector = TwoPhaseEjector(c.nozzle_efficiency, c.mixing_efficiency,
                                 c.diffuser_efficiency)

        def trial(values):
            mu, psep = np.exp(values)
            vapour = ThermodynamicState.from_pressure_quality(fluid, psep, 1)
            liquid = ThermodynamicState.from_pressure_quality(fluid, psep, 0)
            suction = ThermodynamicState.from_pressure_temperature(
                fluid, psep, vapour.temperature_C + c.superheat_K)
            ihx_specific = suction.enthalpy_kJ_kg - vapour.enthalpy_kJ_kg
            primary = ThermodynamicState.from_pressure_enthalpy(
                fluid, pcd, water_sc.enthalpy_kJ_kg - ihx_specific)
            result = ejector.evaluate(fluid, primary, secondary, mu)
            required_quality = 1 / (1 + mu)
            latent = vapour.enthalpy_kJ_kg - liquid.enthalpy_kJ_kg
            residual = np.array([
                math.log(result.outlet.pressure_Pa / psep),
                (result.outlet.enthalpy_kJ_kg - liquid.enthalpy_kJ_kg) / latent
                - required_quality,
            ])
            return residual, (mu, psep, vapour, liquid, suction, primary, result)

        saturated_vapour = ThermodynamicState.from_pressure_quality(fluid, pev, 1)
        saturated_liquid = ThermodynamicState.from_pressure_quality(fluid, pev, 0)
        seed_mu = max(0.02, min(20.0,
            (saturated_vapour.enthalpy_kJ_kg - water_sc.enthalpy_kJ_kg)
            / (secondary.enthalpy_kJ_kg - saturated_liquid.enthalpy_kJ_kg)))
        bounds = (np.log([1e-5, pev * (1 + 1e-8)]),
                  np.log([50.0, pmax]))
        best = None

        def objective(values):
            return trial(values)[0]

        # Retry another initial pressure only if the first solve fails. This is
        # a physical balance closure, not optimization of an arbitrary pressure.
        for lift in (1.02, 1.10):
            initial = np.log([seed_mu, min(pev * lift, math.sqrt(pev * pmax))])
            try:
                root = least_squares(objective, initial, bounds=bounds,
                                     xtol=1e-10, ftol=1e-10, gtol=1e-10,
                                     max_nfev=45)
                residual, solved = trial(root.x)
            except ValueError:
                continue
            error = float(np.max(np.abs(residual)))
            if best is None or error < best[0]:
                best = error, solved
            if error < 1e-8:
                break
        if best is None or best[0] > 1e-7:
            raise ValueError("Ejector/IHX/separator mass and pressure closure failed.")
        closure, (mu, psep, vapour, liquid, suction, primary, result) = best
        if result.outlet.quality is None or not 0 < result.outlet.quality < 1:
            raise ValueError("The ejector outlet must be two-phase for separation.")

        # Check the counterflow IHX along its enthalpy profile, not just its ends.
        ihx_specific = suction.enthalpy_kJ_kg - vapour.enthalpy_kJ_kg
        approaches = []
        for fraction in np.linspace(0, 1, 9):
            hot = ThermodynamicState.from_pressure_enthalpy(
                fluid, pcd, water_sc.enthalpy_kJ_kg - fraction * ihx_specific)
            cold = ThermodynamicState.from_pressure_enthalpy(
                fluid, psep, suction.enthalpy_kJ_kg - fraction * ihx_specific)
            approaches.append(hot.temperature_C - cold.temperature_C)
        approach = min(approaches)
        if approach < c.ihx_minimum_approach_K - 1e-6:
            raise ValueError("The IHX cannot provide suction superheat at its pinch.")
        compression = Compressor(c.compressor_isentropic_efficiency,
                                 c.motor_efficiency,
                                 c.compressor_efficiency_model).compress(fluid, suction, pcd)
        if compression.outlet.quality is not None and compression.outlet.quality < 1:
            raise ValueError("Ejector-cycle compressor discharge is not dry vapour.")
        expansion = expander_model.expand(fluid, liquid, pev) if c.use_expander else None
        valve = (expansion.outlet if expansion is not None
                 else ExpansionValve().expand(fluid, liquid, pev))
        qcond = compression.outlet.enthalpy_kJ_kg - condenser.enthalpy_kJ_kg
        qev = secondary.enthalpy_kJ_kg - valve.enthalpy_kJ_kg
        if qcond <= 0 or qev <= 0:
            raise ValueError("The ejector cycle has non-positive exchanger duties.")
        mass = c.heating_capacity_kW / qcond
        evap_mass = mu * mass
        qsc = mass * c.external_subcooling_specific_heat_kJ_kg
        shaft = mass * compression.specific_shaft_work_kJ_kg
        electric = mass * compression.specific_electrical_work_kJ_kg
        expander_power = (evap_mass * expansion.specific_shaft_work_kJ_kg
                          if expansion is not None else 0.0)
        recovered = c.expander_recovery_efficiency * expander_power
        unrecovered = expander_power - recovered
        net_shaft = shaft - recovered
        net_electric = electric - recovered / c.motor_efficiency
        if not math.isfinite(net_shaft) or net_shaft <= 0 or net_electric <= 0:
            raise ValueError("Ejector/expander cycle requires positive net motor power.")
        evap_heat = evap_mass * qev
        energy_error = c.heating_capacity_kW + qsc - shaft - evap_heat + expander_power
        system_error = c.heating_capacity_kW + qsc + unrecovered - evap_heat - net_shaft
        mass_error = mass - result.outlet.quality * (mass + evap_mass)
        if abs(energy_error) > 1e-6 * (c.heating_capacity_kW + qsc):
            raise ValueError("The ejector cycle does not close its energy balance.")
        source = c.heat_source.evaluate(evap_heat)
        if not source.feasible:
            raise ValueError("The heat source cannot supply the ejector evaporator.")
        return EjectorCycleResult(
            config=c, evaporation_temperature_C=tev,
            states={"suction": suction, "discharge": compression.outlet,
                    "condenser_out": condenser, "subcooler_out": water_sc,
                    "motive_in": primary, "nozzle_out": result.nozzle_outlet,
                    "mixing": result.mixing_state, "ejector_out": result.outlet,
                    "separator_vapour": vapour, "separator_liquid": liquid,
                    "evaporator_in": valve, "evaporator_out": secondary},
            ejector=result, separator_pressure_bar=psep / 1e5,
            evaporator_pressure_bar=pev / 1e5, entrainment_ratio=mu,
            separator_vapor_quality=result.outlet.quality,
            refrigerant_mass_flow_kg_s=mass, evaporator_mass_flow_kg_s=evap_mass,
            evaporator_heat_kW=evap_heat, condenser_heat_kW=c.heating_capacity_kW,
            external_subcooler_heat_kW=qsc, ihx_heat_kW=mass * ihx_specific,
            ihx_minimum_approach_K=approach, compressor_shaft_power_kW=shaft,
            compressor_electrical_power_kW=electric,
            compressor_isentropic_efficiency=compression.isentropic_efficiency,
            pressure_ratio=compression.pressure_ratio,
            heating_COP=(c.heating_capacity_kW + qsc) / net_electric,
            energy_balance_error_kW=energy_error,
            separator_mass_balance_error_kg_s=mass_error,
            ihx_balance_error_kW=mass * ((water_sc.enthalpy_kJ_kg-primary.enthalpy_kJ_kg)
                                        - (suction.enthalpy_kJ_kg-vapour.enthalpy_kJ_kg)),
            closure_residual=closure, heat_source=source,
            expander_shaft_power_kW=expander_power,
            recovered_power_kW=recovered,
            unrecovered_expander_power_kW=unrecovered,
            net_shaft_power_kW=net_shaft,
            net_electrical_power_kW=net_electric,
            system_energy_balance_error_kW=system_error,
            expander=expansion,
        )
