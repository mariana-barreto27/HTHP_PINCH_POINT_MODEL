"""Pequena camada de acesso ao CoolProp, com unidades explícitas."""

from functools import lru_cache

from CoolProp.CoolProp import PropsSI


KELVIN_OFFSET = 273.15

# Os refrigerantes atuais do projeto, R410A e R245fa, são reconhecidos
# diretamente pelo CoolProp. O dicionário permanece disponível para futuros
# fluidos que possam exigir um identificador alternativo.
REFRIGERANT_ALIASES = {}


def to_kelvin(temperature_C: float) -> float:
    return temperature_C + KELVIN_OFFSET


def to_celsius(temperature_K: float) -> float:
    return temperature_K - KELVIN_OFFSET


def resolve_refrigerant(refrigerant: str) -> str:
    """Converte nomes de projeto em identificadores aceitos pelo CoolProp."""
    return REFRIGERANT_ALIASES.get(refrigerant.strip().upper(), refrigerant)


@lru_cache(maxsize=200_000)
def props_si_cached(
    output: str,
    input_1: str,
    value_1: float,
    input_2: str,
    value_2: float,
    refrigerant: str,
) -> float:
    """Evita repetir chamadas caras do CoolProp em varreduras paramétricas."""
    return PropsSI(
        output,
        input_1,
        value_1,
        input_2,
        value_2,
        resolve_refrigerant(refrigerant),
    )


@lru_cache(maxsize=128)
def props_si_constant_cached(output: str, refrigerant: str) -> float:
    return PropsSI(output, resolve_refrigerant(refrigerant))


def saturation_pressure_Pa(
    refrigerant: str,
    temperature_C: float,
    quality: float = 0.0,
) -> float:
    return props_si_cached(
        "P",
        "T",
        to_kelvin(temperature_C),
        "Q",
        quality,
        refrigerant,
    )


def critical_temperature_C(refrigerant: str) -> float:
    return to_celsius(props_si_constant_cached("Tcrit", refrigerant))

