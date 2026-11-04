"""Representação de um ponto termodinâmico do refrigerante."""

from dataclasses import dataclass
import math

from hthp.thermo.properties import state_properties_cached, to_celsius, to_kelvin


@dataclass(frozen=True)
class ThermodynamicState:
    pressure_Pa: float
    temperature_C: float
    enthalpy_kJ_kg: float
    entropy_kJ_kgK: float
    quality: float | None

    @property
    def pressure_bar(self) -> float:
        return self.pressure_Pa / 1.0e5

    @classmethod
    def from_pressure_temperature(
        cls,
        refrigerant: str,
        pressure_Pa: float,
        temperature_C: float,
    ) -> "ThermodynamicState":
        temperature_K = to_kelvin(temperature_C)
        _, enthalpy, entropy, raw_quality = state_properties_cached(
            "P", pressure_Pa, "T", temperature_K, refrigerant)
        quality = _quality_or_none(raw_quality)
        return cls(
            pressure_Pa=pressure_Pa,
            temperature_C=temperature_C,
            enthalpy_kJ_kg=enthalpy / 1000.0,
            entropy_kJ_kgK=entropy / 1000.0,
            quality=quality,
        )

    @classmethod
    def from_pressure_enthalpy(
        cls,
        refrigerant: str,
        pressure_Pa: float,
        enthalpy_kJ_kg: float,
    ) -> "ThermodynamicState":
        enthalpy = enthalpy_kJ_kg * 1000.0
        temperature_K, _, entropy, raw_quality = state_properties_cached(
            "P", pressure_Pa, "H", enthalpy, refrigerant)
        quality = _quality_or_none(raw_quality)
        return cls(
            pressure_Pa=pressure_Pa,
            temperature_C=to_celsius(temperature_K),
            enthalpy_kJ_kg=enthalpy_kJ_kg,
            entropy_kJ_kgK=entropy / 1000.0,
            quality=quality,
        )

    @classmethod
    def from_pressure_quality(
        cls,
        refrigerant: str,
        pressure_Pa: float,
        quality: float,
    ) -> "ThermodynamicState":
        if not 0.0 <= quality <= 1.0:
            raise ValueError("O título deve estar entre 0 e 1.")
        temperature_K, enthalpy, entropy, _ = state_properties_cached(
            "P", pressure_Pa, "Q", quality, refrigerant)
        return cls(
            pressure_Pa=pressure_Pa,
            temperature_C=to_celsius(temperature_K),
            enthalpy_kJ_kg=enthalpy / 1000.0,
            entropy_kJ_kgK=entropy / 1000.0,
            quality=quality,
        )


def _quality_or_none(quality: float) -> float | None:
    if math.isfinite(quality) and 0.0 <= quality <= 1.0:
        return quality
    return None
