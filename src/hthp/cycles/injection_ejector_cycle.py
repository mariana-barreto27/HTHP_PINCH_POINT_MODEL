"""Exploratory injection + ejector circuits, not a published-apparatus replica.

Flash mode: condenser -> valve -> injection flash tank at P_inj. Its vapour
goes to the interstage mixer; its liquid drives an ejector after the IHX.
Economizer mode: condenser liquid splits. Injection liquid expands to P_inj,
boils in the economizer, then goes to the mixer. The remaining liquid is
subcooled by the economizer and IHX, and drives the ejector at P_cond.

In BOTH modes the ejector separator at P_sep is a second, distinct separator.
Its vapour goes through the IHX and compressor step 1, then mixes with injected
vapour before compressor step 2. Its liquid expands to the evaporator, whose
outlet is the ejector secondary inlet. P_evap < P_sep < P_inj < P_cond.
With y=m_inj/m_total and mu=m_evap/m_motive, m_motive=(1-y)*m_total and
m_evap=mu*(1-y)*m_total. No ejector energy recovery is counted as shaft work.
"""

from dataclasses import dataclass
import math
import numpy as np
from scipy.optimize import least_squares

from hthp.components.compressor import Compressor
from hthp.components.ejector import EjectorResult, TwoPhaseEjector
from hthp.components.evaporator import Evaporator
from hthp.components.expansion_valve import ExpansionValve
from hthp.components.flash_tank import FlashTank
from hthp.components.mixer import Mixer
from hthp.cycles.ejector_cycle import EjectorCycleConfig
from hthp.heat_sources.base import HeatSourceEvaluation
from hthp.thermo.properties import critical_temperature_C, saturation_pressure_Pa
from hthp.thermo.state import ThermodynamicState


@dataclass(frozen=True)
class InjectionEjectorCycleConfig(EjectorCycleConfig):
    intermediate_pressure_bar: float | None = None
    injection_mode: str = "flash_tank"
    economizer_effectiveness: float = 0.90
    economizer_minimum_approach_K: float = 5.0


@dataclass(frozen=True)
class InjectionEjectorCycleResult:
    config: InjectionEjectorCycleConfig
    evaporation_temperature_C: float
    states: dict[str, ThermodynamicState]
    ejector: EjectorResult
    intermediate_pressure_bar: float
    geometric_mean_pressure_bar: float
    separator_pressure_bar: float
    evaporator_pressure_bar: float
    entrainment_ratio: float
    separator_vapor_quality: float
    injection_mass_fraction: float
    total_refrigerant_mass_flow_kg_s: float
    main_refrigerant_mass_flow_kg_s: float
    evaporator_mass_flow_kg_s: float
    injected_vapor_mass_flow_kg_s: float
    evaporator_heat_kW: float
    condenser_heat_kW: float
    external_subcooler_heat_kW: float
    economizer_heat_kW: float
    economizer_minimum_approach_K: float | None
    ihx_heat_kW: float
    ihx_minimum_approach_K: float
    low_compressor_shaft_power_kW: float
    high_compressor_shaft_power_kW: float
    total_shaft_power_kW: float
    low_compressor_electrical_power_kW: float
    high_compressor_electrical_power_kW: float
    total_electrical_power_kW: float
    low_compressor_isentropic_efficiency: float
    high_compressor_isentropic_efficiency: float
    compressor_raw_isentropic_efficiencies: tuple[float, float]
    compressor_efficiency_limit_statuses: tuple[str, str]
    low_stage_pressure_ratio: float
    high_stage_pressure_ratio: float
    heating_COP: float
    motor_loss_kW: float
    energy_balance_error_kW: float
    injection_balance_error_kW: float
    economizer_balance_error_kW: float
    separator_mass_balance_error_kg_s: float
    separator_energy_balance_error_kW: float
    ihx_balance_error_kW: float
    closure_residual: float
    heat_source: HeatSourceEvaluation

    @property
    def refrigerant_mass_flow_kg_s(self):
        return self.total_refrigerant_mass_flow_kg_s

    @property
    def relative_energy_balance_error(self):
        return abs(self.energy_balance_error_kW) / self.condenser_heat_kW


class InjectionEjectorCycle:
    def __init__(self, config: InjectionEjectorCycleConfig):
        self.config = config

    def solve(self):
        c = self.config
        fluid = c.refrigerant
        tev = c.heat_source.evaporation_temperature_C()
        self._validate(tev)
        secondary = Evaporator(tev, c.superheat_K).outlet_state(fluid)
        pev = secondary.pressure_Pa
        pcd = saturation_pressure_Pa(fluid, c.condensation_temperature_C)
        geometric_pressure = math.sqrt(pev * pcd)
        pinj = (geometric_pressure if c.intermediate_pressure_bar is None
                else c.intermediate_pressure_bar * 1e5)
        if not math.isfinite(pinj) or not pev < pinj < pcd:
            raise ValueError("Injection pressure must lie between evaporation and condensation.")
        condenser = (ThermodynamicState.from_pressure_quality(fluid, pcd, 0)
                     if c.subcooling_K == 0 else
                     ThermodynamicState.from_pressure_temperature(
                         fluid, pcd, c.condensation_temperature_C - c.subcooling_K))
        water_sc = ThermodynamicState.from_pressure_enthalpy(
            fluid, pcd, condenser.enthalpy_kJ_kg - c.external_subcooling_specific_heat_kJ_kg)
        if water_sc.quality is not None and water_sc.quality > 0:
            raise ValueError("Injection/ejector condenser outlet must be liquid.")
        injection_in = ExpansionValve().expand(fluid, water_sc, pinj)
        injection_vapour = ThermodynamicState.from_pressure_quality(fluid, pinj, 1)
        econ_approach = None
        main_specific_cooling = injection_specific_heating = 0.0
        if c.injection_mode == "flash_tank":
            separated = FlashTank().separate(fluid, injection_in)
            y = separated.vapor_mass_fraction
            main_hot_in = separated.saturated_liquid
            injection_vapour = separated.saturated_vapor
        else:
            available = (water_sc.temperature_C - injection_vapour.temperature_C
                         - c.economizer_minimum_approach_K)
            if available <= 0:
                raise ValueError("No temperature head for the injection economizer.")
            main_hot_in = ThermodynamicState.from_pressure_temperature(
                fluid, pcd, water_sc.temperature_C - c.economizer_effectiveness * available)
            main_specific_cooling = water_sc.enthalpy_kJ_kg - main_hot_in.enthalpy_kJ_kg
            injection_specific_heating = injection_vapour.enthalpy_kJ_kg - injection_in.enthalpy_kJ_kg
            if main_specific_cooling <= 0 or injection_specific_heating <= 0:
                raise ValueError("The economizer must subcool main liquid and evaporate injection.")
            ratio = main_specific_cooling / injection_specific_heating
            y = ratio / (1 + ratio)
            econ_approach = self._thermal_approach(
                fluid, pcd, water_sc.enthalpy_kJ_kg, main_hot_in.enthalpy_kJ_kg,
                pinj, injection_vapour.enthalpy_kJ_kg, injection_in.enthalpy_kJ_kg)
            if econ_approach < c.economizer_minimum_approach_K - 1e-6:
                raise ValueError("The injection economizer violates its internal pinch.")
        if not 0 < y < 1:
            raise ValueError("Injection must leave positive vapour and main-stream flows.")
        main_fraction = 1 - y
        maximum_separator_temperature = (main_hot_in.temperature_C - c.superheat_K
                                         - c.ihx_minimum_approach_K)
        if maximum_separator_temperature <= tev + 1e-6:
            raise ValueError("No temperature head for the injection/ejector IHX.")
        pmax = min(pinj * (1 - 1e-8), saturation_pressure_Pa(
            fluid, maximum_separator_temperature, quality=1))
        if pmax <= pev * (1 + 1e-7):
            raise ValueError("No feasible ejector separator pressure below injection pressure.")
        ejector = TwoPhaseEjector(c.nozzle_efficiency, c.mixing_efficiency, c.diffuser_efficiency)

        def trial(values):
            mu, psep = np.exp(values)
            vapour = ThermodynamicState.from_pressure_quality(fluid, psep, 1)
            liquid = ThermodynamicState.from_pressure_quality(fluid, psep, 0)
            suction = ThermodynamicState.from_pressure_temperature(
                fluid, psep, vapour.temperature_C + c.superheat_K)
            ihx_specific = suction.enthalpy_kJ_kg - vapour.enthalpy_kJ_kg
            primary = ThermodynamicState.from_pressure_enthalpy(
                fluid, main_hot_in.pressure_Pa, main_hot_in.enthalpy_kJ_kg - ihx_specific)
            result = ejector.evaluate(fluid, primary, secondary, mu)
            latent = vapour.enthalpy_kJ_kg - liquid.enthalpy_kJ_kg
            residual = np.array([
                math.log(result.outlet.pressure_Pa / psep),
                (result.outlet.enthalpy_kJ_kg - liquid.enthalpy_kJ_kg) / latent - 1 / (1 + mu)])
            return residual, (mu, psep, vapour, liquid, suction, primary, result)

        ev_vapour = ThermodynamicState.from_pressure_quality(fluid, pev, 1)
        ev_liquid = ThermodynamicState.from_pressure_quality(fluid, pev, 0)
        seed_mu = max(0.02, min(20.0,
            (ev_vapour.enthalpy_kJ_kg - main_hot_in.enthalpy_kJ_kg)
            / (secondary.enthalpy_kJ_kg - ev_liquid.enthalpy_kJ_kg)))
        bounds = np.log([1e-5, pev * (1 + 1e-8)]), np.log([50.0, pmax])
        best = None
        for lift in (1.02, 1.10):
            initial = np.log([seed_mu, min(pev * lift, math.sqrt(pev * pmax))])
            try:
                root = least_squares(lambda values: trial(values)[0], initial, bounds=bounds,
                                     xtol=1e-10, ftol=1e-10, gtol=1e-10, max_nfev=60)
                residual, solved = trial(root.x)
            except ValueError:
                continue
            error = float(np.max(np.abs(residual)))
            if best is None or error < best[0]:
                best = error, solved
            if error < 1e-8:
                break
        if best is None or best[0] > 1e-7:
            raise ValueError("Injection/ejector mass and separator pressure closure failed.")
        closure, (mu, psep, vapour, liquid, suction, primary, result) = best
        if result.outlet.quality is None or not 0 < result.outlet.quality < 1:
            raise ValueError("The ejector must deliver a two-phase mixture for separation.")
        approach = self._thermal_approach(
            fluid, main_hot_in.pressure_Pa, main_hot_in.enthalpy_kJ_kg,
            primary.enthalpy_kJ_kg, psep, suction.enthalpy_kJ_kg, vapour.enthalpy_kJ_kg)
        if approach < c.ihx_minimum_approach_K - 1e-6:
            raise ValueError("The injection/ejector IHX violates its internal pinch.")
        compressor = Compressor(c.compressor_isentropic_efficiency,
                                c.motor_efficiency, c.compressor_efficiency_model)
        low = compressor.compress(fluid, suction, pinj)
        mixed = Mixer().mix(fluid, pinj, [(main_fraction, low.outlet), (y, injection_vapour)])
        high = compressor.compress(fluid, mixed, pcd)
        for state in (low.outlet, mixed, high.outlet):
            if state.quality is not None and state.quality < 1:
                raise ValueError("Injection/ejector compression must remain dry vapour.")
        evap_in = ExpansionValve().expand(fluid, liquid, pev)
        qcond = high.outlet.enthalpy_kJ_kg - condenser.enthalpy_kJ_kg
        qevap = secondary.enthalpy_kJ_kg - evap_in.enthalpy_kJ_kg
        if qcond <= 0 or qevap <= 0:
            raise ValueError("Injection/ejector heat exchanger duties must be positive.")
        total_mass = c.heating_capacity_kW / qcond
        main_mass, injection_mass = main_fraction * total_mass, y * total_mass
        evaporator_mass = mu * main_mass
        evap_heat = evaporator_mass * qevap
        qsc = total_mass * c.external_subcooling_specific_heat_kJ_kg
        low_work = main_mass * low.specific_shaft_work_kJ_kg
        high_work = total_mass * high.specific_shaft_work_kJ_kg
        low_electric = main_mass * low.specific_electrical_work_kJ_kg
        high_electric = total_mass * high.specific_electrical_work_kJ_kg
        work, electrical = low_work + high_work, low_electric + high_electric
        useful = c.heating_capacity_kW + qsc
        energy_error = useful - evap_heat - work
        injection_error = (total_mass * water_sc.enthalpy_kJ_kg
                           - main_mass * main_hot_in.enthalpy_kJ_kg
                           - injection_mass * injection_vapour.enthalpy_kJ_kg)
        econ_error = main_mass * main_specific_cooling - injection_mass * injection_specific_heating
        sep_mass_error = main_mass - result.outlet.quality * (main_mass + evaporator_mass)
        sep_energy_error = ((main_mass + evaporator_mass) * result.outlet.enthalpy_kJ_kg
                            - main_mass * vapour.enthalpy_kJ_kg
                            - evaporator_mass * liquid.enthalpy_kJ_kg)
        ihx_specific = suction.enthalpy_kJ_kg - vapour.enthalpy_kJ_kg
        ihx_error = main_mass * (main_hot_in.enthalpy_kJ_kg - primary.enthalpy_kJ_kg - ihx_specific)
        if abs(energy_error) > 1e-6 * useful:
            raise ValueError("The injection/ejector cycle does not close its energy balance.")
        source = c.heat_source.evaluate(evap_heat)
        if not source.feasible:
            raise ValueError("The heat source cannot supply the injection/ejector evaporator.")
        return InjectionEjectorCycleResult(
            config=c, evaporation_temperature_C=tev,
            states={"suction": suction, "first_discharge": low.outlet, "mixed": mixed,
                    "discharge": high.outlet, "condenser_out": condenser, "subcooler_out": water_sc,
                    "injection_in": injection_in, "injection_vapour": injection_vapour,
                    "main_after_injection_hx": main_hot_in, "motive_in": primary,
                    "nozzle_out": result.nozzle_outlet, "mixing": result.mixing_state,
                    "ejector_out": result.outlet, "separator_vapour": vapour,
                    "separator_liquid": liquid, "evaporator_in": evap_in, "evaporator_out": secondary},
            ejector=result, intermediate_pressure_bar=pinj / 1e5,
            geometric_mean_pressure_bar=geometric_pressure / 1e5,
            separator_pressure_bar=psep / 1e5, evaporator_pressure_bar=pev / 1e5,
            entrainment_ratio=mu, separator_vapor_quality=result.outlet.quality,
            injection_mass_fraction=y, total_refrigerant_mass_flow_kg_s=total_mass,
            main_refrigerant_mass_flow_kg_s=main_mass, evaporator_mass_flow_kg_s=evaporator_mass,
            injected_vapor_mass_flow_kg_s=injection_mass, evaporator_heat_kW=evap_heat,
            condenser_heat_kW=c.heating_capacity_kW, external_subcooler_heat_kW=qsc,
            economizer_heat_kW=main_mass * main_specific_cooling,
            economizer_minimum_approach_K=econ_approach,
            ihx_heat_kW=main_mass * ihx_specific, ihx_minimum_approach_K=approach,
            low_compressor_shaft_power_kW=low_work, high_compressor_shaft_power_kW=high_work,
            total_shaft_power_kW=work, low_compressor_electrical_power_kW=low_electric,
            high_compressor_electrical_power_kW=high_electric, total_electrical_power_kW=electrical,
            low_compressor_isentropic_efficiency=low.isentropic_efficiency,
            high_compressor_isentropic_efficiency=high.isentropic_efficiency,
            compressor_raw_isentropic_efficiencies=(low.raw_isentropic_efficiency,
                                                    high.raw_isentropic_efficiency),
            compressor_efficiency_limit_statuses=(low.efficiency_limit_status,
                                                  high.efficiency_limit_status),
            low_stage_pressure_ratio=pinj / psep, high_stage_pressure_ratio=pcd / pinj,
            heating_COP=useful / electrical, motor_loss_kW=electrical - work,
            energy_balance_error_kW=energy_error, injection_balance_error_kW=injection_error,
            economizer_balance_error_kW=econ_error, separator_mass_balance_error_kg_s=sep_mass_error,
            separator_energy_balance_error_kW=sep_energy_error, ihx_balance_error_kW=ihx_error,
            closure_residual=closure, heat_source=source)

    @staticmethod
    def _thermal_approach(fluid, ph, hhin, hhout, pc, hcout, hcin):
        approaches = []
        for fraction in np.linspace(0, 1, 9):
            hot = ThermodynamicState.from_pressure_enthalpy(
                fluid, ph, hhin + fraction * (hhout - hhin))
            cold = ThermodynamicState.from_pressure_enthalpy(
                fluid, pc, hcout + fraction * (hcin - hcout))
            approaches.append(hot.temperature_C - cold.temperature_C)
        return min(approaches)

    def _validate(self, tev):
        c = self.config
        values = (tev, c.condensation_temperature_C, c.heating_capacity_kW,
                  c.superheat_K, c.subcooling_K, c.external_subcooling_specific_heat_kJ_kg,
                  c.ihx_minimum_approach_K, c.economizer_effectiveness,
                  c.economizer_minimum_approach_K)
        if (not all(math.isfinite(value) for value in values)
                or c.heating_capacity_kW <= 0 or c.superheat_K <= 0 or c.subcooling_K < 0
                or c.external_subcooling_specific_heat_kJ_kg < 0 or c.ihx_minimum_approach_K <= 0
                or not 0 < c.economizer_effectiveness <= 1 or c.economizer_minimum_approach_K <= 0
                or not tev < c.condensation_temperature_C < critical_temperature_C(c.refrigerant)):
            raise ValueError("Invalid injection/ejector temperatures, duty or heat exchanger settings.")
        if c.injection_mode not in ("flash_tank", "economizer"):
            raise ValueError("Injection mode must be flash_tank or economizer.")
        if getattr(c, "use_expander", False):
            raise ValueError("This two-component model does not include an additional expander.")

