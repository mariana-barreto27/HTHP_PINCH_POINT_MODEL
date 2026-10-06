"""Ciclo de dois estágios com economizador e injeção de vapor."""

from dataclasses import dataclass
import math
import numpy as np
from scipy.integrate import trapezoid

from hthp.components.compressor import Compressor
from hthp.components.compressor_performance import IsentropicEfficiencyModel
from hthp.components.condenser import Condenser
from hthp.components.evaporator import Evaporator
from hthp.components.expansion_valve import ExpansionValve
from hthp.components.mixer import Mixer
from hthp.heat_sources.base import HeatSource, HeatSourceEvaluation
from hthp.thermo.properties import critical_temperature_C, props_si_cached
from hthp.thermo.state import ThermodynamicState


@dataclass(frozen=True)
class EconomizerCycleConfig:
    refrigerant: str
    heat_source: HeatSource
    condensation_temperature_C: float
    heating_capacity_kW: float
    intermediate_pressure_bar: float | None = None
    economizer_effectiveness: float = 0.90
    economizer_minimum_approach_K: float = 5.0
    superheat_K: float = 5.0
    subcooling_K: float = 5.0
    compressor_isentropic_efficiency: float = 0.70
    motor_efficiency: float = 0.95
    compressor_efficiency_model: IsentropicEfficiencyModel | None = None
    external_subcooling_specific_heat_kJ_kg: float = 0.0
    injection_mass_fraction: float | None = None


@dataclass(frozen=True)
class EconomizerCycleResult:
    config: EconomizerCycleConfig
    evaporation_temperature_C: float
    states: dict[str, ThermodynamicState]
    intermediate_pressure_bar: float
    geometric_mean_pressure_bar: float
    injection_mass_fraction: float
    total_refrigerant_mass_flow_kg_s: float
    evaporator_mass_flow_kg_s: float
    injected_vapor_mass_flow_kg_s: float
    economizer_heat_kW: float
    evaporator_heat_kW: float
    condenser_heat_kW: float
    external_subcooler_heat_kW: float
    low_compressor_shaft_power_kW: float
    high_compressor_shaft_power_kW: float
    total_shaft_power_kW: float
    low_compressor_electrical_power_kW: float
    high_compressor_electrical_power_kW: float
    low_compressor_isentropic_efficiency: float
    high_compressor_isentropic_efficiency: float
    compressor_raw_isentropic_efficiencies: tuple[float, float]
    compressor_efficiency_limit_statuses: tuple[str, str]
    total_electrical_power_kW: float
    motor_loss_kW: float
    heating_COP: float
    low_stage_pressure_ratio: float
    high_stage_pressure_ratio: float
    energy_balance_error_kW: float
    economizer_balance_error_kW: float
    heat_source: HeatSourceEvaluation
    economizer_actual_minimum_approach_K: float
    economizer_required_UA_kW_K: float

    @property
    def relative_energy_balance_error(self) -> float:
        return abs(self.energy_balance_error_kW) / self.condenser_heat_kW


class EconomizerCycle:
    """Economizador refrigerante-refrigerante sem tanque flash."""

    def __init__(self, config: EconomizerCycleConfig) -> None:
        self.config = config

    def solve(self) -> EconomizerCycleResult:
        config = self.config
        evaporation_temperature = config.heat_source.evaporation_temperature_C()
        self._validate(evaporation_temperature)

        evaporator = Evaporator(evaporation_temperature, config.superheat_K)
        condenser = Condenser(
            config.condensation_temperature_C,
            config.subcooling_K,
        )
        compressor = Compressor(
            config.compressor_isentropic_efficiency,
            config.motor_efficiency,
            config.compressor_efficiency_model,
        )
        valve = ExpansionValve()

        state_1 = evaporator.outlet_state(config.refrigerant)
        state_5 = condenser.outlet_state(config.refrigerant)
        state_5_external = ThermodynamicState.from_pressure_enthalpy(
            config.refrigerant,
            state_5.pressure_Pa,
            state_5.enthalpy_kJ_kg
            - config.external_subcooling_specific_heat_kJ_kg,
        )
        low_pressure = state_1.pressure_Pa
        high_pressure = state_5.pressure_Pa
        geometric_pressure = math.sqrt(low_pressure * high_pressure)
        intermediate_pressure = (
            config.intermediate_pressure_bar * 1.0e5
            if config.intermediate_pressure_bar is not None
            else geometric_pressure
        )
        if not low_pressure < intermediate_pressure < high_pressure:
            raise ValueError(
                "A pressão de injeção deve ficar entre evaporação e condensação."
            )

        injection_vapor = ThermodynamicState.from_pressure_quality(
            config.refrigerant,
            intermediate_pressure,
            1.0,
        )
        injection_after_valve = valve.expand(
            config.refrigerant,
            state_5_external,
            intermediate_pressure,
        )
        minimum_main_outlet_temperature = (
            injection_vapor.temperature_C
            + config.economizer_minimum_approach_K
        )
        available_temperature_difference = (
            state_5_external.temperature_C - minimum_main_outlet_temperature
        )
        if available_temperature_difference <= 0.0:
            raise ValueError(
                "Não há diferença de temperatura disponível no economizador."
            )
        injection_specific_heating = injection_vapor.enthalpy_kJ_kg-injection_after_valve.enthalpy_kJ_kg
        if injection_specific_heating <= 0.0:
            raise ValueError('A corrente de injeção não pode atingir vapor saturado recebendo calor.')
        if config.injection_mass_fraction is None:
            # Compatibilidade para chamadas antigas: fechamento térmico dos 90%.
            main_outlet_temperature = state_5_external.temperature_C - config.economizer_effectiveness*available_temperature_difference
            main_after_economizer = ThermodynamicState.from_pressure_temperature(
                config.refrigerant,high_pressure,main_outlet_temperature)
        else:
            # Fração relativa à vazão TOTAL no condensador. Não impõe T de saída.
            x = config.injection_mass_fraction
            cooling = x/(1.0-x)*injection_specific_heating
            main_after_economizer = ThermodynamicState.from_pressure_enthalpy(
                config.refrigerant,high_pressure,state_5_external.enthalpy_kJ_kg-cooling)
        main_after_valve = valve.expand(
            config.refrigerant,
            main_after_economizer,
            low_pressure,
        )

        main_specific_cooling = (
            state_5_external.enthalpy_kJ_kg
            - main_after_economizer.enthalpy_kJ_kg
        )
        injection_specific_heating = (
            injection_vapor.enthalpy_kJ_kg
            - injection_after_valve.enthalpy_kJ_kg
        )
        if main_specific_cooling <= 0.0:
            raise ValueError("O economizador não subresfria a corrente principal.")
        if injection_specific_heating <= 0.0:
            raise ValueError("A corrente de injeção não evapora no economizador.")
        injection_to_main_ratio = (
            main_specific_cooling / injection_specific_heating
        )
        injection_fraction = injection_to_main_ratio / (
            1.0 + injection_to_main_ratio
        )
        if not 0.0 < injection_fraction < 1.0:
            raise ValueError("A fração de injeção do economizador é inválida.")
        main_fraction = 1.0 - injection_fraction
        # Perfis alinhados em calor, incluindo a fronteira de fase da injeção.
        duty_per_total_mass = injection_fraction*injection_specific_heating
        isothermal_injection = injection_after_valve.quality is not None
        profile_grid = set(np.linspace(0.0,1.0,9 if isothermal_injection else 33))
        hf = ThermodynamicState.from_pressure_quality(config.refrigerant,intermediate_pressure,0).enthalpy_kJ_kg
        phase_position = 1.0-(hf-injection_after_valve.enthalpy_kJ_kg)/injection_specific_heating
        if 0 < phase_position < 1:
            profile_grid.add(float(phase_position))
        profile_grid = np.array(sorted(profile_grid))
        differences = []
        for position in profile_grid:
            hot_t = props_si_cached('T','P',high_pressure,'H',
                (state_5_external.enthalpy_kJ_kg-position*main_specific_cooling)*1000,config.refrigerant)-273.15
            cold_t = injection_vapor.temperature_C if isothermal_injection else props_si_cached('T','P',intermediate_pressure,'H',
                (injection_after_valve.enthalpy_kJ_kg+(1-position)*injection_specific_heating)*1000,config.refrigerant)-273.15
            differences.append(hot_t-cold_t)
        actual_pinch = min(differences)
        if actual_pinch < config.economizer_minimum_approach_K-1e-7 or actual_pinch <= 0:
            raise ValueError(f'Pinch do economizador insuficiente: {actual_pinch:.5f} K.')

        low_compression = compressor.compress(
            config.refrigerant,
            state_1,
            intermediate_pressure,
        )
        state_2 = low_compression.outlet
        state_3 = Mixer().mix(
            config.refrigerant,
            intermediate_pressure,
            [
                (main_fraction, state_2),
                (injection_fraction, injection_vapor),
            ],
        )
        high_compression = compressor.compress(
            config.refrigerant,
            state_3,
            high_pressure,
        )
        state_4 = high_compression.outlet

        specific_condenser_heat = (
            state_4.enthalpy_kJ_kg - state_5.enthalpy_kJ_kg
        )
        specific_evaporator_heat = (
            state_1.enthalpy_kJ_kg - main_after_valve.enthalpy_kJ_kg
        )
        if specific_condenser_heat <= 0.0:
            raise ValueError("O condensador não rejeita calor nesta condição.")
        if specific_evaporator_heat <= 0.0:
            raise ValueError("O evaporador não absorve calor nesta condição.")

        total_mass_flow = config.heating_capacity_kW / specific_condenser_heat
        main_mass_flow = main_fraction * total_mass_flow
        injection_mass_flow = injection_fraction * total_mass_flow
        external_subcooler_heat = (
            total_mass_flow * config.external_subcooling_specific_heat_kJ_kg
        )
        total_useful_heat = config.heating_capacity_kW + external_subcooler_heat
        evaporator_heat = main_mass_flow * specific_evaporator_heat
        economizer_hot_heat = main_mass_flow * main_specific_cooling
        economizer_cold_heat = (
            injection_mass_flow * injection_specific_heating
        )

        low_shaft_power = (
            main_mass_flow * low_compression.specific_shaft_work_kJ_kg
        )
        high_shaft_power = (
            total_mass_flow * high_compression.specific_shaft_work_kJ_kg
        )
        low_electrical_power = (
            main_mass_flow * low_compression.specific_electrical_work_kJ_kg
        )
        high_electrical_power = (
            total_mass_flow * high_compression.specific_electrical_work_kJ_kg
        )
        total_shaft_power = low_shaft_power + high_shaft_power
        total_electrical_power = low_electrical_power + high_electrical_power

        source_evaluation = config.heat_source.evaluate(evaporator_heat)
        if not source_evaluation.feasible:
            raise ValueError(
                "A fonte de calor não fornece a carga exigida pelo evaporador."
            )

        return EconomizerCycleResult(
            config=config,
            evaporation_temperature_C=evaporation_temperature,
            states={
                "1": state_1,
                "2": state_2,
                "3": state_3,
                "4": state_4,
                "5": state_5,
                "5E": state_5_external,
                "6": main_after_economizer,
                "7": main_after_valve,
                "8": injection_after_valve,
                "9": injection_vapor,
            },
            intermediate_pressure_bar=intermediate_pressure / 1.0e5,
            geometric_mean_pressure_bar=geometric_pressure / 1.0e5,
            injection_mass_fraction=injection_fraction,
            total_refrigerant_mass_flow_kg_s=total_mass_flow,
            evaporator_mass_flow_kg_s=main_mass_flow,
            injected_vapor_mass_flow_kg_s=injection_mass_flow,
            economizer_heat_kW=economizer_hot_heat,
            evaporator_heat_kW=evaporator_heat,
            condenser_heat_kW=config.heating_capacity_kW,
            external_subcooler_heat_kW=external_subcooler_heat,
            low_compressor_shaft_power_kW=low_shaft_power,
            high_compressor_shaft_power_kW=high_shaft_power,
            total_shaft_power_kW=total_shaft_power,
            low_compressor_electrical_power_kW=low_electrical_power,
            high_compressor_electrical_power_kW=high_electrical_power,
            low_compressor_isentropic_efficiency=(
                low_compression.isentropic_efficiency
            ),
            high_compressor_isentropic_efficiency=(
                high_compression.isentropic_efficiency
            ),
            compressor_raw_isentropic_efficiencies=(
                low_compression.raw_isentropic_efficiency,
                high_compression.raw_isentropic_efficiency,
            ),
            compressor_efficiency_limit_statuses=(
                low_compression.efficiency_limit_status,
                high_compression.efficiency_limit_status,
            ),
            total_electrical_power_kW=total_electrical_power,
            motor_loss_kW=total_electrical_power - total_shaft_power,
            heating_COP=total_useful_heat / total_electrical_power,
            low_stage_pressure_ratio=intermediate_pressure / low_pressure,
            high_stage_pressure_ratio=high_pressure / intermediate_pressure,
            energy_balance_error_kW=(
                total_useful_heat - evaporator_heat - total_shaft_power
            ),
            economizer_balance_error_kW=(
                economizer_hot_heat - economizer_cold_heat
            ),
            heat_source=source_evaluation,
            economizer_actual_minimum_approach_K=actual_pinch,
            economizer_required_UA_kW_K=total_mass_flow*duty_per_total_mass*float(trapezoid(1/np.array(differences),profile_grid)),
        )

    def _validate(self, evaporation_temperature_C: float) -> None:
        config = self.config
        if config.heating_capacity_kW <= 0.0:
            raise ValueError("A capacidade de aquecimento deve ser positiva.")
        if config.injection_mass_fraction is not None and not 0 < config.injection_mass_fraction < 1:
            raise ValueError('A fração mássica de injeção deve estar entre 0 e 1.')
        if config.injection_mass_fraction is None and not 0.0 < config.economizer_effectiveness <= 1.0:
            raise ValueError("A efetividade do economizador deve estar entre 0 e 1.")
        if config.economizer_minimum_approach_K < 0.0:
            raise ValueError("O pinch do economizador não pode ser negativo.")
        if config.external_subcooling_specific_heat_kJ_kg < 0.0:
            raise ValueError("O subresfriamento externo não pode ser negativo.")
        if evaporation_temperature_C >= config.condensation_temperature_C:
            raise ValueError("A evaporação deve ficar abaixo da condensação.")
        critical = critical_temperature_C(config.refrigerant)
        if config.condensation_temperature_C >= critical:
            raise ValueError(
                "O economizador exige condensação subcrítica abaixo de "
                f"{critical:.2f} °C."
            )
