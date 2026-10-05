"""Contratos comuns para consumidores térmicos do HTHP."""

from dataclasses import dataclass
from typing import Protocol

from hthp.components.external_subcooler import SubcoolerColdStream


@dataclass(frozen=True)
class PreparedHeatSink:
    mode: str
    total_thermal_duty_kW: float
    condensation_temperature_C: float
    pressure_bar: float
    main_inlet_temperature_C: float
    main_outlet_temperature_C: float
    main_inlet_enthalpy_kJ_kg: float
    main_outlet_enthalpy_kJ_kg: float
    subcooler_cold_stream: SubcoolerColdStream
    product_mass_flow_kg_s: float | None = None
    product_outlet_quality: float | None = None


@dataclass(frozen=True)
class HeatSinkResult:
    mode: str
    condensation_temperature_C: float
    pressure_bar: float
    total_useful_heat_kW: float
    main_condenser_heat_kW: float
    external_subcooler_heat_kW: float
    main_stream_mass_flow_kg_s: float
    subcooler_stream_mass_flow_kg_s: float
    final_stream_mass_flow_kg_s: float
    main_inlet_temperature_C: float
    main_outlet_temperature_C: float
    subcooler_outlet_temperature_C: float
    final_outlet_temperature_C: float
    final_outlet_quality: float | None
    energy_balance_error_kW: float


class HeatSink(Protocol):
    def prepare(
        self,
        total_thermal_duty_kW: float,
        condenser_pinch_K: float,
    ) -> PreparedHeatSink:
        """Determina a condição de condensação e a corrente do subresfriador."""

    def evaluate(
        self,
        prepared: PreparedHeatSink,
        main_condenser_heat_kW: float,
        external_subcooler_heat_kW: float,
        subcooler_outlet_temperature_C: float,
    ) -> HeatSinkResult:
        """Fecha os balanços da corrente aquecida após resolver o ciclo."""
