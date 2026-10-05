"""Consumidor térmico que transforma água de alimentação em vapor saturado."""

from dataclasses import dataclass

from hthp.components.external_subcooler import SubcoolerColdStream
from hthp.heat_sinks.base import HeatSinkResult, PreparedHeatSink
from hthp.thermo.properties import props_si_cached, to_celsius, to_kelvin


@dataclass(frozen=True)
class SteamHeatSink:
    target_temperature_C: float = 120.0
    feedwater_temperature_C: float = 25.0
    outlet_quality: float = 1.0
    fluid: str = "Water"

    def __post_init__(self) -> None:
        if self.feedwater_temperature_C >= self.target_temperature_C:
            raise ValueError("A água de alimentação deve entrar mais fria.")
        if not 0.0 <= self.outlet_quality <= 1.0:
            raise ValueError("A qualidade final deve ficar entre zero e um.")

    def prepare(
        self,
        total_thermal_duty_kW: float,
        condenser_pinch_K: float,
    ) -> PreparedHeatSink:
        if total_thermal_duty_kW <= 0.0 or condenser_pinch_K <= 0.0:
            raise ValueError("A carga e o pinch devem ser positivos.")
        pressure_Pa = props_si_cached(
            "P",
            "T",
            to_kelvin(self.target_temperature_C),
            "Q",
            0.0,
            self.fluid,
        )
        feedwater_enthalpy = props_si_cached(
            "H",
            "P",
            pressure_Pa,
            "T",
            to_kelvin(self.feedwater_temperature_C),
            self.fluid,
        ) / 1000.0
        saturated_liquid_enthalpy = props_si_cached(
            "H", "P", pressure_Pa, "Q", 0.0, self.fluid
        ) / 1000.0
        saturated_vapor_enthalpy = props_si_cached(
            "H", "P", pressure_Pa, "Q", 1.0, self.fluid
        ) / 1000.0
        outlet_enthalpy = saturated_liquid_enthalpy + self.outlet_quality * (
            saturated_vapor_enthalpy - saturated_liquid_enthalpy
        )
        mass_flow = total_thermal_duty_kW / (
            outlet_enthalpy - feedwater_enthalpy
        )
        pressure_bar = pressure_Pa / 1.0e5
        return PreparedHeatSink(
            mode="steam",
            total_thermal_duty_kW=total_thermal_duty_kW,
            condensation_temperature_C=(
                self.target_temperature_C + condenser_pinch_K
            ),
            pressure_bar=pressure_bar,
            main_inlet_temperature_C=self.feedwater_temperature_C,
            main_outlet_temperature_C=self.target_temperature_C,
            main_inlet_enthalpy_kJ_kg=feedwater_enthalpy,
            main_outlet_enthalpy_kJ_kg=outlet_enthalpy,
            subcooler_cold_stream=SubcoolerColdStream(
                fluid=self.fluid,
                inlet_temperature_C=self.feedwater_temperature_C,
                pressure_bar=pressure_bar,
                mass_flow_kg_s=mass_flow,
            ),
            product_mass_flow_kg_s=mass_flow,
            product_outlet_quality=self.outlet_quality,
        )

    def evaluate(
        self,
        prepared: PreparedHeatSink,
        main_condenser_heat_kW: float,
        external_subcooler_heat_kW: float,
        subcooler_outlet_temperature_C: float,
    ) -> HeatSinkResult:
        mass_flow = prepared.product_mass_flow_kg_s
        if mass_flow is None:
            raise ValueError("A vazão de vapor não foi preparada.")
        pressure_Pa = prepared.pressure_bar * 1.0e5
        after_subcooler_enthalpy = (
            prepared.main_inlet_enthalpy_kJ_kg
            + external_subcooler_heat_kW / mass_flow
        )
        after_subcooler_temperature_C = to_celsius(
            props_si_cached(
                "T",
                "P",
                pressure_Pa,
                "H",
                after_subcooler_enthalpy * 1000.0,
                self.fluid,
            )
        )
        expected_main_heat = mass_flow * (
            prepared.main_outlet_enthalpy_kJ_kg
            - after_subcooler_enthalpy
        )
        energy_error = main_condenser_heat_kW - expected_main_heat
        return HeatSinkResult(
            mode=prepared.mode,
            condensation_temperature_C=prepared.condensation_temperature_C,
            pressure_bar=prepared.pressure_bar,
            total_useful_heat_kW=(
                main_condenser_heat_kW + external_subcooler_heat_kW
            ),
            main_condenser_heat_kW=main_condenser_heat_kW,
            external_subcooler_heat_kW=external_subcooler_heat_kW,
            main_stream_mass_flow_kg_s=mass_flow,
            subcooler_stream_mass_flow_kg_s=mass_flow,
            final_stream_mass_flow_kg_s=mass_flow,
            main_inlet_temperature_C=after_subcooler_temperature_C,
            main_outlet_temperature_C=prepared.main_outlet_temperature_C,
            subcooler_outlet_temperature_C=subcooler_outlet_temperature_C,
            final_outlet_temperature_C=self.target_temperature_C,
            final_outlet_quality=self.outlet_quality,
            energy_balance_error_kW=energy_error,
        )
