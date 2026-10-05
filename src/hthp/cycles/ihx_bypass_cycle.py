"""Ciclo de alta temperatura com IHX e divisão opcional de vazão."""

from dataclasses import dataclass

from hthp.components.compressor import Compressor
from hthp.components.compressor_performance import IsentropicEfficiencyModel
from hthp.components.condenser import Condenser
from hthp.components.evaporator import Evaporator
from hthp.components.expansion_valve import ExpansionValve
from hthp.heat_sources.base import HeatSource, HeatSourceEvaluation
from hthp.thermo.properties import critical_temperature_C
from hthp.thermo.state import ThermodynamicState


@dataclass(frozen=True)
class IHXBypassCycleConfig:
    refrigerant: str
    heat_source: HeatSource
    condensation_temperature_C: float
    heating_capacity_kW: float
    ihx_fraction: float = 1.00
    ihx_effectiveness: float = 0.70
    ihx_minimum_approach_K: float = 5.0
    superheat_K: float = 5.0
    subcooling_K: float = 5.0
    compressor_isentropic_efficiency: float = 0.70
    motor_efficiency: float = 0.95
    compressor_efficiency_model: IsentropicEfficiencyModel | None = None
    external_subcooling_specific_heat_kJ_kg: float = 0.0


@dataclass(frozen=True)
class IHXBypassCycleResult:
    config: IHXBypassCycleConfig
    evaporation_temperature_C: float
    states: dict[str, ThermodynamicState]
    refrigerant_mass_flow_kg_s: float
    evaporator_heat_kW: float
    condenser_heat_kW: float
    external_subcooler_heat_kW: float
    ihx_heat_kW: float
    compressor_shaft_power_kW: float
    compressor_electrical_power_kW: float
    compressor_isentropic_efficiency: float
    compressor_raw_isentropic_efficiency: float
    compressor_efficiency_limit_status: str
    motor_loss_kW: float
    heating_COP: float
    pressure_ratio: float
    energy_balance_error_kW: float
    heat_source: HeatSourceEvaluation

    @property
    def relative_energy_balance_error(self) -> float:
        return abs(self.energy_balance_error_kW) / self.condenser_heat_kW


class IHXBypassCycle:
    def __init__(self, config: IHXBypassCycleConfig) -> None:
        self.config = config

    def solve(self) -> IHXBypassCycleResult:
        config = self.config
        evaporation_temperature = config.heat_source.evaporation_temperature_C()
        self._validate(evaporation_temperature)

        state_1 = Evaporator(
            evaporation_temperature,
            config.superheat_K,
        ).outlet_state(config.refrigerant)
        state_3 = Condenser(
            config.condensation_temperature_C,
            config.subcooling_K,
        ).outlet_state(config.refrigerant)

        state_3_external = ThermodynamicState.from_pressure_enthalpy(
            config.refrigerant,
            state_3.pressure_Pa,
            state_3.enthalpy_kJ_kg
            - config.external_subcooling_specific_heat_kJ_kg,
        )

        specific_ihx_heat = self._specific_ihx_heat(state_1, state_3_external)
        if config.ihx_fraction > 0.0 and specific_ihx_heat > 0.0:
            cold_branch_enthalpy = state_1.enthalpy_kJ_kg + (
                specific_ihx_heat / config.ihx_fraction
            )
            state_1_ihx = ThermodynamicState.from_pressure_enthalpy(
                config.refrigerant,
                state_1.pressure_Pa,
                cold_branch_enthalpy,
            )
        else:
            state_1_ihx = state_1

        state_1_mixed = ThermodynamicState.from_pressure_enthalpy(
            config.refrigerant,
            state_1.pressure_Pa,
            state_1.enthalpy_kJ_kg + specific_ihx_heat,
        )
        state_4 = ThermodynamicState.from_pressure_enthalpy(
            config.refrigerant,
            state_3.pressure_Pa,
            state_3_external.enthalpy_kJ_kg - specific_ihx_heat,
        )
        compression = Compressor(
            config.compressor_isentropic_efficiency,
            config.motor_efficiency,
            config.compressor_efficiency_model,
        ).compress(
            config.refrigerant,
            state_1_mixed,
            state_3.pressure_Pa,
        )
        state_2 = compression.outlet
        state_5 = ExpansionValve().expand(
            config.refrigerant,
            state_4,
            state_1.pressure_Pa,
        )

        specific_condenser_heat = state_2.enthalpy_kJ_kg - state_3.enthalpy_kJ_kg
        specific_evaporator_heat = state_1.enthalpy_kJ_kg - state_5.enthalpy_kJ_kg
        if specific_condenser_heat <= 0.0:
            raise ValueError("O condensador não rejeita calor nesta condição.")
        if specific_evaporator_heat <= 0.0:
            raise ValueError("O evaporador não absorve calor nesta condição.")

        mass_flow = config.heating_capacity_kW / specific_condenser_heat
        external_subcooler_heat = (
            mass_flow * config.external_subcooling_specific_heat_kJ_kg
        )
        total_useful_heat = config.heating_capacity_kW + external_subcooler_heat
        evaporator_heat = mass_flow * specific_evaporator_heat
        shaft_power = mass_flow * compression.specific_shaft_work_kJ_kg
        electrical_power = mass_flow * compression.specific_electrical_work_kJ_kg
        source_evaluation = config.heat_source.evaluate(evaporator_heat)
        if not source_evaluation.feasible:
            raise ValueError("A fonte de calor não fornece a carga exigida.")

        return IHXBypassCycleResult(
            config=config,
            evaporation_temperature_C=evaporation_temperature,
            states={
                "1": state_1,
                "1I": state_1_ihx,
                "1B": state_1,
                "1M": state_1_mixed,
                "2": state_2,
                "3": state_3,
                "3E": state_3_external,
                "4": state_4,
                "5": state_5,
            },
            refrigerant_mass_flow_kg_s=mass_flow,
            evaporator_heat_kW=evaporator_heat,
            condenser_heat_kW=config.heating_capacity_kW,
            external_subcooler_heat_kW=external_subcooler_heat,
            ihx_heat_kW=mass_flow * specific_ihx_heat,
            compressor_shaft_power_kW=shaft_power,
            compressor_electrical_power_kW=electrical_power,
            compressor_isentropic_efficiency=compression.isentropic_efficiency,
            compressor_raw_isentropic_efficiency=(
                compression.raw_isentropic_efficiency
            ),
            compressor_efficiency_limit_status=(
                compression.efficiency_limit_status
            ),
            motor_loss_kW=electrical_power - shaft_power,
            heating_COP=total_useful_heat / electrical_power,
            pressure_ratio=state_3.pressure_Pa / state_1.pressure_Pa,
            energy_balance_error_kW=(
                total_useful_heat - evaporator_heat - shaft_power
            ),
            heat_source=source_evaluation,
        )

    def _specific_ihx_heat(
        self,
        cold_inlet: ThermodynamicState,
        hot_inlet: ThermodynamicState,
    ) -> float:
        config = self.config
        if config.ihx_fraction == 0.0 or config.ihx_effectiveness == 0.0:
            return 0.0

        hot_limit_temperature = (
            cold_inlet.temperature_C + config.ihx_minimum_approach_K
        )
        cold_limit_temperature = (
            hot_inlet.temperature_C - config.ihx_minimum_approach_K
        )
        if hot_limit_temperature > cold_limit_temperature:
            return 0.0

        hot_limit = ThermodynamicState.from_pressure_temperature(
            config.refrigerant,
            hot_inlet.pressure_Pa,
            hot_limit_temperature,
        )
        cold_limit = ThermodynamicState.from_pressure_temperature(
            config.refrigerant,
            cold_inlet.pressure_Pa,
            cold_limit_temperature,
        )
        hot_capacity = hot_inlet.enthalpy_kJ_kg - hot_limit.enthalpy_kJ_kg
        cold_capacity = config.ihx_fraction * (
            cold_limit.enthalpy_kJ_kg - cold_inlet.enthalpy_kJ_kg
        )
        maximum_heat = min(hot_capacity, cold_capacity)
        if maximum_heat <= 0.0:
            return 0.0
        return config.ihx_effectiveness * maximum_heat

    def _validate(self, evaporation_temperature_C: float) -> None:
        config = self.config
        if not 0.0 <= config.ihx_fraction <= 1.0:
            raise ValueError("A fração no IHX deve estar entre 0 e 1.")
        if not 0.0 <= config.ihx_effectiveness <= 1.0:
            raise ValueError("A efetividade do IHX deve estar entre 0 e 1.")
        if config.ihx_minimum_approach_K < 0.0:
            raise ValueError("A aproximação mínima do IHX não pode ser negativa.")
        if config.heating_capacity_kW <= 0.0:
            raise ValueError("A capacidade de aquecimento deve ser positiva.")
        if config.external_subcooling_specific_heat_kJ_kg < 0.0:
            raise ValueError("O subresfriamento externo não pode ser negativo.")
        if evaporation_temperature_C >= config.condensation_temperature_C:
            raise ValueError("A evaporação deve ficar abaixo da condensação.")
        critical = critical_temperature_C(config.refrigerant)
        if config.condensation_temperature_C >= critical:
            raise ValueError(
                "O ciclo com IHX é subcrítico: a condensação deve ficar "
                f"abaixo de {critical:.2f} °C."
            )
