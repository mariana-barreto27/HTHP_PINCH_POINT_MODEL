"""Balanço térmico de água de alimentação até vapor saturado."""

from dataclasses import dataclass

from CoolProp.CoolProp import PropsSI

from hthp.thermo.properties import to_kelvin


@dataclass(frozen=True)
class SteamGeneratorConfig:
    target_steam_temperature_C: float
    thermal_duty_kW: float
    feedwater_temperature_C: float = 25.0
    outlet_quality: float = 1.0
    heat_exchanger_approach_K: float = 5.0
    fluid: str = "Water"


@dataclass(frozen=True)
class SteamGeneratorResult:
    config: SteamGeneratorConfig
    saturation_pressure_bar: float
    refrigerant_condensing_temperature_C: float
    feedwater_specific_enthalpy_kJ_kg: float
    saturated_liquid_specific_enthalpy_kJ_kg: float
    saturated_vapor_specific_enthalpy_kJ_kg: float
    outlet_specific_enthalpy_kJ_kg: float
    specific_heat_input_kJ_kg: float
    steam_mass_flow_kg_s: float
    feedwater_preheating_duty_kW: float
    evaporation_duty_kW: float
    energy_balance_error_kW: float

    @property
    def relative_energy_balance_error(self) -> float:
        return abs(self.energy_balance_error_kW) / self.config.thermal_duty_kW


class SteamGenerator:
    def __init__(self, config: SteamGeneratorConfig) -> None:
        self.config = config

    def solve(self) -> SteamGeneratorResult:
        config = self.config
        self._validate()
        steam_temperature_K = to_kelvin(config.target_steam_temperature_C)
        feedwater_temperature_K = to_kelvin(config.feedwater_temperature_C)
        pressure_Pa = PropsSI("P", "T", steam_temperature_K, "Q", 0, config.fluid)
        saturated_liquid_enthalpy = (
            PropsSI("H", "P", pressure_Pa, "Q", 0, config.fluid) / 1000.0
        )
        saturated_vapor_enthalpy = (
            PropsSI("H", "P", pressure_Pa, "Q", 1, config.fluid) / 1000.0
        )
        feedwater_enthalpy = (
            PropsSI(
                "H",
                "P",
                pressure_Pa,
                "T",
                feedwater_temperature_K,
                config.fluid,
            )
            / 1000.0
        )
        outlet_enthalpy = saturated_liquid_enthalpy + config.outlet_quality * (
            saturated_vapor_enthalpy - saturated_liquid_enthalpy
        )
        specific_heat_input = outlet_enthalpy - feedwater_enthalpy
        if specific_heat_input <= 0.0:
            raise ValueError("Steam generation requires a positive enthalpy rise.")

        mass_flow = config.thermal_duty_kW / specific_heat_input
        preheating_duty = mass_flow * (
            saturated_liquid_enthalpy - feedwater_enthalpy
        )
        evaporation_duty = mass_flow * (
            outlet_enthalpy - saturated_liquid_enthalpy
        )
        balance_error = (
            config.thermal_duty_kW - preheating_duty - evaporation_duty
        )
        return SteamGeneratorResult(
            config=config,
            saturation_pressure_bar=pressure_Pa / 1.0e5,
            refrigerant_condensing_temperature_C=(
                config.target_steam_temperature_C
                + config.heat_exchanger_approach_K
            ),
            feedwater_specific_enthalpy_kJ_kg=feedwater_enthalpy,
            saturated_liquid_specific_enthalpy_kJ_kg=saturated_liquid_enthalpy,
            saturated_vapor_specific_enthalpy_kJ_kg=saturated_vapor_enthalpy,
            outlet_specific_enthalpy_kJ_kg=outlet_enthalpy,
            specific_heat_input_kJ_kg=specific_heat_input,
            steam_mass_flow_kg_s=mass_flow,
            feedwater_preheating_duty_kW=preheating_duty,
            evaporation_duty_kW=evaporation_duty,
            energy_balance_error_kW=balance_error,
        )

    def _validate(self) -> None:
        config = self.config
        if config.thermal_duty_kW <= 0.0:
            raise ValueError("Steam-generator thermal duty must be positive.")
        if config.feedwater_temperature_C >= config.target_steam_temperature_C:
            raise ValueError(
                "Feedwater temperature must remain below steam temperature."
            )
        if not 0.0 <= config.outlet_quality <= 1.0:
            raise ValueError("Steam quality must be between 0 and 1.")
        if config.heat_exchanger_approach_K <= 0.0:
            raise ValueError("Heat-exchanger approach must be positive.")
