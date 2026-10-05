"""Consumidor com reposição pré-aquecida e mistura antes do condensador."""

from dataclasses import dataclass

from hthp.components.external_subcooler import SubcoolerColdStream
from hthp.heat_sinks.base import HeatSinkResult, PreparedHeatSink
from hthp.thermo.properties import props_si_cached, to_celsius, to_kelvin


@dataclass(frozen=True)
class HotWaterHeatSink:
    main_inlet_temperature_C: float = 110.0
    main_outlet_temperature_C: float = 115.0
    pressure_bar: float = 5.0
    makeup_inlet_temperature_C: float = 25.0
    makeup_mass_flow_kg_s: float = 190.0 / 3600.0
    fluid: str = "Water"

    def __post_init__(self) -> None:
        if self.main_outlet_temperature_C <= self.main_inlet_temperature_C:
            raise ValueError("A água principal deve ser aquecida.")
        if self.pressure_bar <= 0.0 or self.makeup_mass_flow_kg_s <= 0.0:
            raise ValueError("Pressão e vazão de reposição devem ser positivas.")

    def _enthalpy_kJ_kg(self, temperature_C: float) -> float:
        return props_si_cached(
            "H",
            "P",
            self.pressure_bar * 1.0e5,
            "T",
            to_kelvin(temperature_C),
            self.fluid,
        ) / 1000.0

    def prepare(
        self,
        total_thermal_duty_kW: float,
        condenser_pinch_K: float,
    ) -> PreparedHeatSink:
        if total_thermal_duty_kW <= 0.0 or condenser_pinch_K <= 0.0:
            raise ValueError("A carga e o pinch devem ser positivos.")
        return PreparedHeatSink(
            mode="hot_water",
            total_thermal_duty_kW=total_thermal_duty_kW,
            condensation_temperature_C=(
                self.main_outlet_temperature_C + condenser_pinch_K
            ),
            pressure_bar=self.pressure_bar,
            main_inlet_temperature_C=self.main_inlet_temperature_C,
            main_outlet_temperature_C=self.main_outlet_temperature_C,
            main_inlet_enthalpy_kJ_kg=self._enthalpy_kJ_kg(
                self.main_inlet_temperature_C
            ),
            main_outlet_enthalpy_kJ_kg=self._enthalpy_kJ_kg(
                self.main_outlet_temperature_C
            ),
            subcooler_cold_stream=SubcoolerColdStream(
                fluid=self.fluid,
                inlet_temperature_C=self.makeup_inlet_temperature_C,
                pressure_bar=self.pressure_bar,
                mass_flow_kg_s=self.makeup_mass_flow_kg_s,
            ),
        )

    def evaluate(
        self,
        prepared: PreparedHeatSink,
        main_condenser_heat_kW: float,
        external_subcooler_heat_kW: float,
        subcooler_outlet_temperature_C: float,
    ) -> HeatSinkResult:
        main_enthalpy_rise = (
            prepared.main_outlet_enthalpy_kJ_kg
            - prepared.main_inlet_enthalpy_kJ_kg
        )
        if main_enthalpy_rise <= 0.0:
            raise ValueError("O aumento de entalpia da água deve ser positivo.")

        makeup_mass_flow = prepared.subcooler_cold_stream.mass_flow_kg_s
        makeup_outlet_enthalpy = self._enthalpy_kJ_kg(
            subcooler_outlet_temperature_C
        )
        heat_to_finish_makeup_kW = makeup_mass_flow * (
            prepared.main_outlet_enthalpy_kJ_kg
            - makeup_outlet_enthalpy
        )
        heat_available_for_return_kW = (
            main_condenser_heat_kW - heat_to_finish_makeup_kW
        )
        if heat_available_for_return_kW <= 0.0:
            raise ValueError(
                "O condensador não fornece calor suficiente para levar a "
                "água de reposição pré-aquecida até a temperatura final."
            )

        main_mass_flow = heat_available_for_return_kW / main_enthalpy_rise
        mixed_mass_flow = main_mass_flow + makeup_mass_flow
        mixed_inlet_enthalpy = (
            main_mass_flow * prepared.main_inlet_enthalpy_kJ_kg
            + makeup_mass_flow * makeup_outlet_enthalpy
        ) / mixed_mass_flow
        mixed_inlet_temperature_C = to_celsius(
            props_si_cached(
                "T",
                "P",
                self.pressure_bar * 1.0e5,
                "H",
                mixed_inlet_enthalpy * 1000.0,
                self.fluid,
            )
        )
        expected_main_heat_kW = mixed_mass_flow * (
            prepared.main_outlet_enthalpy_kJ_kg
            - mixed_inlet_enthalpy
        )
        makeup_inlet_enthalpy = self._enthalpy_kJ_kg(
            prepared.subcooler_cold_stream.inlet_temperature_C
        )
        useful_product_heat_kW = (
            main_mass_flow
            * (
                prepared.main_outlet_enthalpy_kJ_kg
                - prepared.main_inlet_enthalpy_kJ_kg
            )
            + makeup_mass_flow
            * (
                prepared.main_outlet_enthalpy_kJ_kg
                - makeup_inlet_enthalpy
            )
        )
        return HeatSinkResult(
            mode=prepared.mode,
            condensation_temperature_C=prepared.condensation_temperature_C,
            pressure_bar=prepared.pressure_bar,
            total_useful_heat_kW=(
                main_condenser_heat_kW + external_subcooler_heat_kW
            ),
            main_condenser_heat_kW=main_condenser_heat_kW,
            external_subcooler_heat_kW=external_subcooler_heat_kW,
            main_stream_mass_flow_kg_s=main_mass_flow,
            subcooler_stream_mass_flow_kg_s=makeup_mass_flow,
            final_stream_mass_flow_kg_s=mixed_mass_flow,
            main_inlet_temperature_C=mixed_inlet_temperature_C,
            main_outlet_temperature_C=prepared.main_outlet_temperature_C,
            subcooler_outlet_temperature_C=subcooler_outlet_temperature_C,
            final_outlet_temperature_C=prepared.main_outlet_temperature_C,
            final_outlet_quality=None,
            energy_balance_error_kW=(
                prepared.total_thermal_duty_kW - useful_product_heat_kW
                + main_condenser_heat_kW - expected_main_heat_kW
            ),
        )
