"""Ciclo de dois estágios com flash tank e injeção de vapor."""

from dataclasses import dataclass
import math

from hthp.components.compressor import Compressor
from hthp.components.compressor_performance import IsentropicEfficiencyModel
from hthp.components.condenser import Condenser
from hthp.components.evaporator import Evaporator
from hthp.components.expansion_valve import ExpansionValve
from hthp.components.flash_tank import FlashTank
from hthp.components.mixer import Mixer
from hthp.heat_sources.base import HeatSource, HeatSourceEvaluation
from hthp.thermo.properties import critical_temperature_C
from hthp.thermo.state import ThermodynamicState


@dataclass(frozen=True)
class FlashTankCycleConfig:
    refrigerant: str
    heat_source: HeatSource
    condensation_temperature_C: float
    heating_capacity_kW: float
    intermediate_pressure_bar: float | None = None
    superheat_K: float = 5.0
    subcooling_K: float = 5.0
    compressor_isentropic_efficiency: float = 0.70
    motor_efficiency: float = 0.95
    compressor_efficiency_model: IsentropicEfficiencyModel | None = None
    external_subcooling_specific_heat_kJ_kg: float = 0.0


@dataclass(frozen=True)
class FlashTankCycleResult:
    config: FlashTankCycleConfig
    evaporation_temperature_C: float
    states: dict[str, ThermodynamicState]
    intermediate_pressure_bar: float
    geometric_mean_pressure_bar: float
    flash_vapor_fraction: float
    total_refrigerant_mass_flow_kg_s: float
    evaporator_mass_flow_kg_s: float
    injected_vapor_mass_flow_kg_s: float
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
    heat_source: HeatSourceEvaluation

    @property
    def relative_energy_balance_error(self) -> float:
        return abs(self.energy_balance_error_kW) / self.condenser_heat_kW


class FlashTankCycle:
    def __init__(self, config: FlashTankCycleConfig) -> None:
        self.config = config

    def solve(self) -> FlashTankCycleResult:
        config = self.config
        evaporation_temperature = config.heat_source.evaporation_temperature_C()
        self._validate_temperatures(evaporation_temperature)

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
                "A pressão intermediária deve ficar entre evaporação e condensação."
            )

        state_6 = valve.expand(
            config.refrigerant,
            state_5_external,
            intermediate_pressure,
        )
        separation = FlashTank().separate(config.refrigerant, state_6)
        vapor_fraction = separation.vapor_mass_fraction
        state_6_liquid = separation.saturated_liquid
        state_6_vapor = separation.saturated_vapor
        state_7 = valve.expand(
            config.refrigerant,
            state_6_liquid,
            low_pressure,
        )

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
                (1.0 - vapor_fraction, state_2),
                (vapor_fraction, state_6_vapor),
            ],
        )
        high_compression = compressor.compress(
            config.refrigerant,
            state_3,
            high_pressure,
        )
        state_4 = high_compression.outlet

        specific_condenser_heat = state_4.enthalpy_kJ_kg - state_5.enthalpy_kJ_kg
        specific_evaporator_heat = state_1.enthalpy_kJ_kg - state_7.enthalpy_kJ_kg
        if specific_condenser_heat <= 0.0:
            raise ValueError("O condensador não rejeita calor nesta condição.")
        if specific_evaporator_heat <= 0.0:
            raise ValueError("O evaporador não absorve calor nesta condição.")

        total_mass_flow = config.heating_capacity_kW / specific_condenser_heat
        external_subcooler_heat = (
            total_mass_flow * config.external_subcooling_specific_heat_kJ_kg
        )
        total_useful_heat = config.heating_capacity_kW + external_subcooler_heat
        evaporator_mass_flow = (1.0 - vapor_fraction) * total_mass_flow
        injection_mass_flow = vapor_fraction * total_mass_flow
        evaporator_heat = evaporator_mass_flow * specific_evaporator_heat

        low_shaft_power = (
            evaporator_mass_flow * low_compression.specific_shaft_work_kJ_kg
        )
        high_shaft_power = (
            total_mass_flow * high_compression.specific_shaft_work_kJ_kg
        )
        low_electrical_power = (
            evaporator_mass_flow * low_compression.specific_electrical_work_kJ_kg
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

        return FlashTankCycleResult(
            config=config,
            evaporation_temperature_C=evaporation_temperature,
            states={
                "1": state_1,
                "2": state_2,
                "3": state_3,
                "4": state_4,
                "5": state_5,
                "5E": state_5_external,
                "6": state_6,
                "6L": state_6_liquid,
                "6V": state_6_vapor,
                "7": state_7,
            },
            intermediate_pressure_bar=intermediate_pressure / 1.0e5,
            geometric_mean_pressure_bar=geometric_pressure / 1.0e5,
            flash_vapor_fraction=vapor_fraction,
            total_refrigerant_mass_flow_kg_s=total_mass_flow,
            evaporator_mass_flow_kg_s=evaporator_mass_flow,
            injected_vapor_mass_flow_kg_s=injection_mass_flow,
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
            heat_source=source_evaluation,
        )

    def _validate_temperatures(self, evaporation_temperature_C: float) -> None:
        config = self.config
        if config.heating_capacity_kW <= 0.0:
            raise ValueError("A capacidade de aquecimento deve ser positiva.")
        if config.external_subcooling_specific_heat_kJ_kg < 0.0:
            raise ValueError("O subresfriamento externo não pode ser negativo.")
        if evaporation_temperature_C >= config.condensation_temperature_C:
            raise ValueError("A evaporação deve ficar abaixo da condensação.")
        critical = critical_temperature_C(config.refrigerant)
        if config.condensation_temperature_C >= critical:
            raise ValueError(
                "O ciclo com flash tank é subcrítico: a condensação deve ficar "
                f"abaixo de {critical:.2f} °C."
            )
