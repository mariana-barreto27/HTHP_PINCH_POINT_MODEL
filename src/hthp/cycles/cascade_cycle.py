"""Cascata com tecnologias configuráveis nos estágios de baixa e alta."""

from dataclasses import dataclass
from typing import Literal

from hthp.cycles.flash_tank_cycle import FlashTankCycle, FlashTankCycleConfig
from hthp.cycles.economizer_cycle import EconomizerCycle, EconomizerCycleConfig
from hthp.cycles.flash_ihx_cycle import FlashIHXCycle, FlashIHXCycleConfig
from hthp.cycles.ihx_bypass_cycle import IHXBypassCycle, IHXBypassCycleConfig
from hthp.cycles.simple_cycle import SimpleCycleConfig, SimpleVaporCompressionCycle
from hthp.components.compressor_performance import IsentropicEfficiencyModel
from hthp.heat_sources.base import HeatSource
from hthp.heat_sources.fixed_temperature import FixedTemperatureHeatSource
from hthp.thermo.state import ThermodynamicState


StageTechnology = Literal[
    "simple",
    "flash_tank",
    "economizer",
    "ihx_bypass",
    "flash_ihx",
]


@dataclass(frozen=True)
class CascadeStageOptions:
    refrigerant: str = "R245fa"
    technology: StageTechnology = "simple"
    superheat_K: float = 5.0
    subcooling_K: float = 5.0
    compressor_isentropic_efficiency: float = 0.70
    motor_efficiency: float = 0.95
    compressor_efficiency_model: IsentropicEfficiencyModel | None = None
    flash_intermediate_pressure_bar: float | None = None
    economizer_intermediate_pressure_bar: float | None = None
    economizer_effectiveness: float = 0.90
    economizer_minimum_approach_K: float = 5.0
    ihx_fraction: float = 1.00
    ihx_effectiveness: float = 0.70
    ihx_minimum_approach_K: float = 5.0
    external_subcooling_specific_heat_kJ_kg: float = 0.0


@dataclass(frozen=True)
class CascadeCycleConfig:
    external_heat_source: HeatSource
    final_condensation_temperature_C: float
    heating_capacity_kW: float
    low_stage: CascadeStageOptions
    high_stage: CascadeStageOptions
    high_stage_evaporation_temperature_C: float = 35.0
    cascade_approach_K: float = 5.0


@dataclass(frozen=True)
class CascadeStageResult:
    technology: StageTechnology
    refrigerant: str
    evaporation_temperature_C: float
    condensation_temperature_C: float
    condenser_heat_kW: float
    external_subcooler_heat_kW: float
    evaporator_heat_kW: float
    shaft_power_kW: float
    electrical_power_kW: float
    heating_COP: float
    refrigerant_mass_flow_kg_s: float
    intermediate_pressure_bar: float | None
    compressor_isentropic_efficiencies: tuple[float, ...]
    compressor_raw_isentropic_efficiencies: tuple[float, ...]
    compressor_efficiency_limit_statuses: tuple[str, ...]
    compressor_mass_flows_kg_s: tuple[float, ...]
    compressor_suction_state_keys: tuple[str, ...]
    compressor_discharge_pressures_Pa: tuple[float, ...]
    maximum_discharge_temperature_C: float
    relative_energy_balance_error: float
    states: dict[str, ThermodynamicState]
    injection_mass_fraction: float | None = None
    economizer_heat_kW: float = 0.0


@dataclass(frozen=True)
class CascadeCycleResult:
    config: CascadeCycleConfig
    low_stage: CascadeStageResult
    high_stage: CascadeStageResult
    low_stage_condensation_temperature_C: float
    high_stage_evaporation_temperature_C: float
    interstage_heat_kW: float
    total_shaft_power_kW: float
    total_electrical_power_kW: float
    overall_heating_COP: float
    cascade_heat_balance_error_kW: float
    overall_energy_balance_error_kW: float

    @property
    def relative_overall_energy_balance_error(self) -> float:
        return abs(self.overall_energy_balance_error_kW) / self.config.heating_capacity_kW


class CascadeCycle:
    def __init__(self, config: CascadeCycleConfig) -> None:
        self.config = config

    def solve(self) -> CascadeCycleResult:
        config = self.config
        if config.cascade_approach_K <= 0.0:
            raise ValueError("A aproximação da cascata deve ser positiva.")
        if config.heating_capacity_kW <= 0.0:
            raise ValueError("A capacidade final deve ser positiva.")
        if (
            config.high_stage_evaporation_temperature_C
            >= config.final_condensation_temperature_C
        ):
            raise ValueError("A evaporação do estágio alto deve ficar abaixo da saída final.")

        low_condensation_temperature = (
            config.high_stage_evaporation_temperature_C + config.cascade_approach_K
        )
        high_source = FixedTemperatureHeatSource(
            config.high_stage_evaporation_temperature_C
        )
        high_result = self.solve_stage(
            config.high_stage,
            high_source,
            config.final_condensation_temperature_C,
            config.heating_capacity_kW,
        )
        low_result = self.solve_stage(
            config.low_stage,
            config.external_heat_source,
            low_condensation_temperature,
            high_result.evaporator_heat_kW,
        )

        total_shaft_power = low_result.shaft_power_kW + high_result.shaft_power_kW
        total_electrical_power = (
            low_result.electrical_power_kW + high_result.electrical_power_kW
        )
        cascade_balance = (
            low_result.condenser_heat_kW - high_result.evaporator_heat_kW
        )
        overall_balance = (
            config.heating_capacity_kW
            - low_result.evaporator_heat_kW
            - total_shaft_power
        )
        return CascadeCycleResult(
            config=config,
            low_stage=low_result,
            high_stage=high_result,
            low_stage_condensation_temperature_C=low_condensation_temperature,
            high_stage_evaporation_temperature_C=(
                config.high_stage_evaporation_temperature_C
            ),
            interstage_heat_kW=high_result.evaporator_heat_kW,
            total_shaft_power_kW=total_shaft_power,
            total_electrical_power_kW=total_electrical_power,
            overall_heating_COP=config.heating_capacity_kW / total_electrical_power,
            cascade_heat_balance_error_kW=cascade_balance,
            overall_energy_balance_error_kW=overall_balance,
        )

    @staticmethod
    def solve_stage(
        options: CascadeStageOptions,
        heat_source: HeatSource,
        condensation_temperature_C: float,
        condenser_heat_kW: float,
    ) -> CascadeStageResult:
        """Resolve um estágio isolado nas condições térmicas informadas."""
        common = {
            "refrigerant": options.refrigerant,
            "heat_source": heat_source,
            "condensation_temperature_C": condensation_temperature_C,
            "heating_capacity_kW": condenser_heat_kW,
            "superheat_K": options.superheat_K,
            "subcooling_K": options.subcooling_K,
            "compressor_isentropic_efficiency": (
                options.compressor_isentropic_efficiency
            ),
            "motor_efficiency": options.motor_efficiency,
            "compressor_efficiency_model": options.compressor_efficiency_model,
            "external_subcooling_specific_heat_kJ_kg": (
                options.external_subcooling_specific_heat_kJ_kg
            ),
        }
        if options.technology == "simple":
            result = SimpleVaporCompressionCycle(SimpleCycleConfig(**common)).solve()
            return CascadeStageResult(
                technology=options.technology,
                refrigerant=options.refrigerant,
                evaporation_temperature_C=result.evaporation_temperature_C,
                condensation_temperature_C=condensation_temperature_C,
                condenser_heat_kW=result.condenser_heat_kW,
                external_subcooler_heat_kW=(
                    result.external_subcooler_heat_kW
                ),
                evaporator_heat_kW=result.evaporator_heat_kW,
                shaft_power_kW=result.compressor_shaft_power_kW,
                electrical_power_kW=result.compressor_electrical_power_kW,
                heating_COP=result.heating_COP,
                refrigerant_mass_flow_kg_s=result.refrigerant_mass_flow_kg_s,
                intermediate_pressure_bar=None,
                compressor_isentropic_efficiencies=(
                    result.compressor_isentropic_efficiency,
                ),
                compressor_raw_isentropic_efficiencies=(
                    result.compressor_raw_isentropic_efficiency,
                ),
                compressor_efficiency_limit_statuses=(
                    result.compressor_efficiency_limit_status,
                ),
                compressor_mass_flows_kg_s=(
                    result.refrigerant_mass_flow_kg_s,
                ),
                compressor_suction_state_keys=("1",),
                compressor_discharge_pressures_Pa=(
                    result.states[2].pressure_Pa,
                ),
                maximum_discharge_temperature_C=result.states[2].temperature_C,
                relative_energy_balance_error=result.relative_energy_balance_error,
                states={str(key): value for key, value in result.states.items()},
            )
        if options.technology == "flash_tank":
            result = FlashTankCycle(
                FlashTankCycleConfig(
                    **common,
                    intermediate_pressure_bar=(
                        options.flash_intermediate_pressure_bar
                    ),
                )
            ).solve()
            return CascadeStageResult(
                technology=options.technology,
                refrigerant=options.refrigerant,
                evaporation_temperature_C=result.evaporation_temperature_C,
                condensation_temperature_C=condensation_temperature_C,
                condenser_heat_kW=result.condenser_heat_kW,
                external_subcooler_heat_kW=(
                    result.external_subcooler_heat_kW
                ),
                evaporator_heat_kW=result.evaporator_heat_kW,
                shaft_power_kW=result.total_shaft_power_kW,
                electrical_power_kW=result.total_electrical_power_kW,
                heating_COP=result.heating_COP,
                refrigerant_mass_flow_kg_s=(
                    result.total_refrigerant_mass_flow_kg_s
                ),
                intermediate_pressure_bar=result.intermediate_pressure_bar,
                compressor_isentropic_efficiencies=(
                    result.low_compressor_isentropic_efficiency,
                    result.high_compressor_isentropic_efficiency,
                ),
                compressor_raw_isentropic_efficiencies=(
                    result.compressor_raw_isentropic_efficiencies
                ),
                compressor_efficiency_limit_statuses=(
                    result.compressor_efficiency_limit_statuses
                ),
                compressor_mass_flows_kg_s=(
                    result.evaporator_mass_flow_kg_s,
                    result.total_refrigerant_mass_flow_kg_s,
                ),
                compressor_suction_state_keys=("1", "3"),
                compressor_discharge_pressures_Pa=(
                    result.states["2"].pressure_Pa,
                    result.states["4"].pressure_Pa,
                ),
                maximum_discharge_temperature_C=max(
                    result.states["2"].temperature_C,
                    result.states["4"].temperature_C,
                ),
                relative_energy_balance_error=result.relative_energy_balance_error,
                states=result.states,
            )
        if options.technology == "economizer":
            result = EconomizerCycle(
                EconomizerCycleConfig(
                    **common,
                    intermediate_pressure_bar=(
                        options.economizer_intermediate_pressure_bar
                    ),
                    economizer_effectiveness=(
                        options.economizer_effectiveness
                    ),
                    economizer_minimum_approach_K=(
                        options.economizer_minimum_approach_K
                    ),
                )
            ).solve()
            return CascadeStageResult(
                technology=options.technology,
                refrigerant=options.refrigerant,
                evaporation_temperature_C=result.evaporation_temperature_C,
                condensation_temperature_C=condensation_temperature_C,
                condenser_heat_kW=result.condenser_heat_kW,
                external_subcooler_heat_kW=(
                    result.external_subcooler_heat_kW
                ),
                evaporator_heat_kW=result.evaporator_heat_kW,
                shaft_power_kW=result.total_shaft_power_kW,
                electrical_power_kW=result.total_electrical_power_kW,
                heating_COP=result.heating_COP,
                refrigerant_mass_flow_kg_s=(
                    result.total_refrigerant_mass_flow_kg_s
                ),
                intermediate_pressure_bar=result.intermediate_pressure_bar,
                compressor_isentropic_efficiencies=(
                    result.low_compressor_isentropic_efficiency,
                    result.high_compressor_isentropic_efficiency,
                ),
                compressor_raw_isentropic_efficiencies=(
                    result.compressor_raw_isentropic_efficiencies
                ),
                compressor_efficiency_limit_statuses=(
                    result.compressor_efficiency_limit_statuses
                ),
                compressor_mass_flows_kg_s=(
                    result.evaporator_mass_flow_kg_s,
                    result.total_refrigerant_mass_flow_kg_s,
                ),
                compressor_suction_state_keys=("1", "3"),
                compressor_discharge_pressures_Pa=(
                    result.states["2"].pressure_Pa,
                    result.states["4"].pressure_Pa,
                ),
                maximum_discharge_temperature_C=max(
                    result.states["2"].temperature_C,
                    result.states["4"].temperature_C,
                ),
                relative_energy_balance_error=(
                    result.relative_energy_balance_error
                ),
                states=result.states,
                injection_mass_fraction=result.injection_mass_fraction,
                economizer_heat_kW=result.economizer_heat_kW,
            )
        if options.technology == "ihx_bypass":
            result = IHXBypassCycle(
                IHXBypassCycleConfig(
                    **common,
                    ihx_fraction=options.ihx_fraction,
                    ihx_effectiveness=options.ihx_effectiveness,
                    ihx_minimum_approach_K=options.ihx_minimum_approach_K,
                )
            ).solve()
            return CascadeStageResult(
                technology=options.technology,
                refrigerant=options.refrigerant,
                evaporation_temperature_C=result.evaporation_temperature_C,
                condensation_temperature_C=condensation_temperature_C,
                condenser_heat_kW=result.condenser_heat_kW,
                external_subcooler_heat_kW=(
                    result.external_subcooler_heat_kW
                ),
                evaporator_heat_kW=result.evaporator_heat_kW,
                shaft_power_kW=result.compressor_shaft_power_kW,
                electrical_power_kW=result.compressor_electrical_power_kW,
                heating_COP=result.heating_COP,
                refrigerant_mass_flow_kg_s=result.refrigerant_mass_flow_kg_s,
                intermediate_pressure_bar=None,
                compressor_isentropic_efficiencies=(
                    result.compressor_isentropic_efficiency,
                ),
                compressor_raw_isentropic_efficiencies=(
                    result.compressor_raw_isentropic_efficiency,
                ),
                compressor_efficiency_limit_statuses=(
                    result.compressor_efficiency_limit_status,
                ),
                compressor_mass_flows_kg_s=(
                    result.refrigerant_mass_flow_kg_s,
                ),
                compressor_suction_state_keys=("1M",),
                compressor_discharge_pressures_Pa=(
                    result.states["2"].pressure_Pa,
                ),
                maximum_discharge_temperature_C=result.states["2"].temperature_C,
                relative_energy_balance_error=result.relative_energy_balance_error,
                states=result.states,
            )
        if options.technology == "flash_ihx":
            result = FlashIHXCycle(
                FlashIHXCycleConfig(
                    **common,
                    intermediate_pressure_bar=(
                        options.flash_intermediate_pressure_bar
                    ),
                    ihx_fraction=options.ihx_fraction,
                    ihx_effectiveness=options.ihx_effectiveness,
                    ihx_minimum_approach_K=options.ihx_minimum_approach_K,
                )
            ).solve()
            return CascadeStageResult(
                technology=options.technology,
                refrigerant=options.refrigerant,
                evaporation_temperature_C=result.evaporation_temperature_C,
                condensation_temperature_C=condensation_temperature_C,
                condenser_heat_kW=result.condenser_heat_kW,
                external_subcooler_heat_kW=(
                    result.external_subcooler_heat_kW
                ),
                evaporator_heat_kW=result.evaporator_heat_kW,
                shaft_power_kW=result.total_shaft_power_kW,
                electrical_power_kW=result.total_electrical_power_kW,
                heating_COP=result.heating_COP,
                refrigerant_mass_flow_kg_s=(
                    result.total_refrigerant_mass_flow_kg_s
                ),
                intermediate_pressure_bar=result.intermediate_pressure_bar,
                compressor_isentropic_efficiencies=(
                    result.low_compressor_isentropic_efficiency,
                    result.high_compressor_isentropic_efficiency,
                ),
                compressor_raw_isentropic_efficiencies=(
                    result.compressor_raw_isentropic_efficiencies
                ),
                compressor_efficiency_limit_statuses=(
                    result.compressor_efficiency_limit_statuses
                ),
                compressor_mass_flows_kg_s=(
                    result.evaporator_mass_flow_kg_s,
                    result.total_refrigerant_mass_flow_kg_s,
                ),
                compressor_suction_state_keys=("1M", "3"),
                compressor_discharge_pressures_Pa=(
                    result.states["2"].pressure_Pa,
                    result.states["4"].pressure_Pa,
                ),
                maximum_discharge_temperature_C=max(
                    result.states["2"].temperature_C,
                    result.states["4"].temperature_C,
                ),
                relative_energy_balance_error=result.relative_energy_balance_error,
                states=result.states,
            )
        raise ValueError(f"Tecnologia de estágio desconhecida: {options.technology}")
