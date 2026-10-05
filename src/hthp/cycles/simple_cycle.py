"""Ciclo subcrítico de estágio único por compressão de vapor."""

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
class SimpleCycleConfig:
    refrigerant: str
    heat_source: HeatSource
    condensation_temperature_C: float
    heating_capacity_kW: float
    superheat_K: float = 5.0
    subcooling_K: float = 5.0
    compressor_isentropic_efficiency: float = 0.70
    motor_efficiency: float = 0.95
    compressor_efficiency_model: IsentropicEfficiencyModel | None = None
    external_subcooling_specific_heat_kJ_kg: float = 0.0


@dataclass(frozen=True)
class SimpleCycleResult:
    config: SimpleCycleConfig
    evaporation_temperature_C: float
    states: dict[int | str, ThermodynamicState]
    refrigerant_mass_flow_kg_s: float
    evaporator_heat_kW: float
    condenser_heat_kW: float
    external_subcooler_heat_kW: float
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


class SimpleVaporCompressionCycle:
    def __init__(self, config: SimpleCycleConfig) -> None:
        self.config = config

    def solve(self) -> SimpleCycleResult:
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
        state_3 = condenser.outlet_state(config.refrigerant)
        state_3_external = ThermodynamicState.from_pressure_enthalpy(
            config.refrigerant,
            state_3.pressure_Pa,
            state_3.enthalpy_kJ_kg
            - config.external_subcooling_specific_heat_kJ_kg,
        )
        compressor_result = compressor.compress(
            config.refrigerant,
            state_1,
            state_3.pressure_Pa,
        )
        state_2 = compressor_result.outlet
        state_4 = valve.expand(
            config.refrigerant,
            state_3_external,
            state_1.pressure_Pa,
        )

        specific_condenser_heat = state_2.enthalpy_kJ_kg - state_3.enthalpy_kJ_kg
        specific_evaporator_heat = state_1.enthalpy_kJ_kg - state_4.enthalpy_kJ_kg
        if specific_condenser_heat <= 0.0:
            raise ValueError(
                "O refrigerante não rejeita calor no condensador nesta condição."
            )
        if specific_evaporator_heat <= 0.0:
            raise ValueError(
                "O refrigerante não consegue absorver calor no evaporador nesta "
                "combinação extrema de temperaturas."
            )

        mass_flow = config.heating_capacity_kW / specific_condenser_heat
        external_subcooler_heat = (
            mass_flow * config.external_subcooling_specific_heat_kJ_kg
        )
        total_useful_heat = config.heating_capacity_kW + external_subcooler_heat
        evaporator_heat = mass_flow * specific_evaporator_heat
        shaft_power = mass_flow * compressor_result.specific_shaft_work_kJ_kg
        electrical_power = (
            mass_flow * compressor_result.specific_electrical_work_kJ_kg
        )
        source_evaluation = config.heat_source.evaluate(evaporator_heat)
        if not source_evaluation.feasible:
            maximum = source_evaluation.maximum_heat_kW
            raise ValueError(
                "A fonte de processo não fornece o calor necessário: "
                f"necessário={evaporator_heat:.2f} kW, "
                f"máximo={maximum:.2f} kW."
            )

        return SimpleCycleResult(
            config=config,
            evaporation_temperature_C=evaporation_temperature,
            states={
                1: state_1,
                2: state_2,
                3: state_3,
                "3E": state_3_external,
                4: state_4,
            },
            refrigerant_mass_flow_kg_s=mass_flow,
            evaporator_heat_kW=evaporator_heat,
            condenser_heat_kW=config.heating_capacity_kW,
            external_subcooler_heat_kW=external_subcooler_heat,
            compressor_shaft_power_kW=shaft_power,
            compressor_electrical_power_kW=electrical_power,
            compressor_isentropic_efficiency=(
                compressor_result.isentropic_efficiency
            ),
            compressor_raw_isentropic_efficiency=(
                compressor_result.raw_isentropic_efficiency
            ),
            compressor_efficiency_limit_status=(
                compressor_result.efficiency_limit_status
            ),
            motor_loss_kW=electrical_power - shaft_power,
            heating_COP=total_useful_heat / electrical_power,
            pressure_ratio=state_3.pressure_Pa / state_1.pressure_Pa,
            energy_balance_error_kW=(
                total_useful_heat - evaporator_heat - shaft_power
            ),
            heat_source=source_evaluation,
        )

    def _validate(self, evaporation_temperature_C: float) -> None:
        config = self.config
        if config.heating_capacity_kW <= 0.0:
            raise ValueError("A capacidade de aquecimento deve ser positiva.")
        if config.external_subcooling_specific_heat_kJ_kg < 0.0:
            raise ValueError("O subresfriamento externo não pode ser negativo.")
        if evaporation_temperature_C >= config.condensation_temperature_C:
            raise ValueError(
                "A temperatura de evaporação deve ser menor que a de condensação."
            )
        critical = critical_temperature_C(config.refrigerant)
        if config.condensation_temperature_C >= critical:
            raise ValueError(
                "Este primeiro modelo é subcrítico: a condensação deve ficar "
                f"abaixo da temperatura crítica ({critical:.2f} °C)."
            )
