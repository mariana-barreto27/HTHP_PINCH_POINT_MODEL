"""Subresfriador externo com efetividade e corrente fria explícitas."""

from dataclasses import dataclass

from hthp.components.heat_exchanger_sizing import (
    HeatExchangerSizingResult,
    logarithmic_mean_temperature_difference_K,
    size_heat_exchanger,
)
from hthp.thermo.properties import props_si_cached, to_celsius, to_kelvin
from hthp.thermo.state import ThermodynamicState


@dataclass(frozen=True)
class SubcoolerColdStream:
    fluid: str
    inlet_temperature_C: float
    pressure_bar: float
    mass_flow_kg_s: float

    def __post_init__(self) -> None:
        if self.pressure_bar <= 0.0:
            raise ValueError("A pressão da corrente fria deve ser positiva.")
        if self.mass_flow_kg_s <= 0.0:
            raise ValueError("A vazão da corrente fria deve ser positiva.")


@dataclass(frozen=True)
class ExternalSubcoolerConfig:
    effectiveness: float = 0.90
    correction_factor: float = 1.0
    require_cold_side_as_c_min: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.effectiveness <= 1.0:
            raise ValueError("A efetividade deve estar entre zero e um.")
        if not 0.0 < self.correction_factor <= 1.0:
            raise ValueError("O fator de correção deve estar entre zero e um.")


@dataclass(frozen=True)
class ExternalSubcoolerResult:
    inlet_state: ThermodynamicState
    outlet_state: ThermodynamicState
    cold_stream: SubcoolerColdStream
    cold_outlet_temperature_C: float
    heat_kW: float
    cold_capacity_rate_kW_K: float
    refrigerant_capacity_rate_kW_K: float
    cold_side_is_c_min: bool
    sizing: HeatExchangerSizingResult


class ExternalSubcooler:
    def __init__(self, config: ExternalSubcoolerConfig) -> None:
        self.config = config

    @staticmethod
    def _specific_heat_kJ_kgK(
        fluid: str,
        temperature_C: float,
        pressure_Pa: float,
    ) -> float:
        return props_si_cached(
            "C",
            "P",
            pressure_Pa,
            "T",
            to_kelvin(temperature_C),
            fluid,
        ) / 1000.0

    def estimate_heat_kW(
        self,
        refrigerant_inlet: ThermodynamicState,
        cold_stream: SubcoolerColdStream,
    ) -> tuple[float, float]:
        """Usa a hipótese recebida de que a água é a corrente C_min."""
        pressure_Pa = cold_stream.pressure_bar * 1.0e5
        cold_cp = self._specific_heat_kJ_kgK(
            cold_stream.fluid,
            cold_stream.inlet_temperature_C,
            pressure_Pa,
        )
        cold_capacity_rate = cold_stream.mass_flow_kg_s * cold_cp
        inlet_difference = (
            refrigerant_inlet.temperature_C - cold_stream.inlet_temperature_C
        )
        if inlet_difference <= 0.0:
            raise ValueError(
                "A corrente fria do subresfriador deve entrar abaixo do "
                "refrigerante."
            )
        maximum_heat = cold_capacity_rate * inlet_difference
        return self.config.effectiveness * maximum_heat, cold_capacity_rate

    def solve(
        self,
        refrigerant: str,
        refrigerant_inlet: ThermodynamicState,
        refrigerant_mass_flow_kg_s: float,
        cold_stream: SubcoolerColdStream,
        prescribed_heat_kW: float | None = None,
    ) -> ExternalSubcoolerResult:
        if refrigerant_mass_flow_kg_s <= 0.0:
            raise ValueError("A vazão do refrigerante deve ser positiva.")
        estimated_heat, cold_capacity_rate = self.estimate_heat_kW(
            refrigerant_inlet,
            cold_stream,
        )
        heat_kW = estimated_heat if prescribed_heat_kW is None else prescribed_heat_kW
        if heat_kW < 0.0:
            raise ValueError("O calor do subresfriador não pode ser negativo.")

        refrigerant_cp = self._specific_heat_kJ_kgK(
            refrigerant,
            refrigerant_inlet.temperature_C,
            refrigerant_inlet.pressure_Pa,
        )
        refrigerant_capacity_rate = (
            refrigerant_mass_flow_kg_s * refrigerant_cp
        )
        cold_side_is_c_min = cold_capacity_rate <= refrigerant_capacity_rate
        if self.config.require_cold_side_as_c_min and not cold_side_is_c_min:
            raise ValueError(
                "A hipótese C_min = corrente fria é inválida: "
                f"C_fria={cold_capacity_rate:.4f} kW/K e "
                f"C_refrigerante={refrigerant_capacity_rate:.4f} kW/K."
            )

        outlet_enthalpy = refrigerant_inlet.enthalpy_kJ_kg - (
            heat_kW / refrigerant_mass_flow_kg_s
        )
        refrigerant_outlet = ThermodynamicState.from_pressure_enthalpy(
            refrigerant,
            refrigerant_inlet.pressure_Pa,
            outlet_enthalpy,
        )

        cold_pressure_Pa = cold_stream.pressure_bar * 1.0e5
        cold_inlet_enthalpy = props_si_cached(
            "H",
            "P",
            cold_pressure_Pa,
            "T",
            to_kelvin(cold_stream.inlet_temperature_C),
            cold_stream.fluid,
        ) / 1000.0
        cold_outlet_enthalpy = cold_inlet_enthalpy + (
            heat_kW / cold_stream.mass_flow_kg_s
        )
        cold_outlet_temperature_C = to_celsius(
            props_si_cached(
                "T",
                "P",
                cold_pressure_Pa,
                "H",
                cold_outlet_enthalpy * 1000.0,
                cold_stream.fluid,
            )
        )
        terminal_difference_1_K = (
            refrigerant_inlet.temperature_C - cold_outlet_temperature_C
        )
        terminal_difference_2_K = (
            refrigerant_outlet.temperature_C - cold_stream.inlet_temperature_C
        )
        if heat_kW == 0.0:
            lmtd_K = logarithmic_mean_temperature_difference_K(
                terminal_difference_1_K,
                terminal_difference_2_K,
            )
            sizing = HeatExchangerSizingResult(
                duty_kW=0.0,
                terminal_temperature_difference_1_K=(
                    terminal_difference_1_K
                ),
                terminal_temperature_difference_2_K=(
                    terminal_difference_2_K
                ),
                lmtd_K=lmtd_K,
                correction_factor=self.config.correction_factor,
                ua_kW_K=0.0,
            )
        else:
            sizing = size_heat_exchanger(
                heat_kW,
                terminal_difference_1_K,
                terminal_difference_2_K,
                self.config.correction_factor,
            )
        return ExternalSubcoolerResult(
            inlet_state=refrigerant_inlet,
            outlet_state=refrigerant_outlet,
            cold_stream=cold_stream,
            cold_outlet_temperature_C=cold_outlet_temperature_C,
            heat_kW=heat_kW,
            cold_capacity_rate_kW_K=cold_capacity_rate,
            refrigerant_capacity_rate_kW_K=refrigerant_capacity_rate,
            cold_side_is_c_min=cold_side_is_c_min,
            sizing=sizing,
        )
