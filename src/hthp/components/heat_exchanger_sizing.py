"""Dimensionamento térmico de trocadores pelo método LMTD."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class HeatExchangerSizingResult:
    duty_kW: float
    terminal_temperature_difference_1_K: float
    terminal_temperature_difference_2_K: float
    lmtd_K: float
    correction_factor: float
    ua_kW_K: float


def logarithmic_mean_temperature_difference_K(
    difference_1_K: float,
    difference_2_K: float,
) -> float:
    """Calcula a diferença média logarítmica entre dois terminais."""
    if difference_1_K <= 0.0 or difference_2_K <= 0.0:
        raise ValueError(
            "As duas diferenças terminais devem ser positivas: "
            f"DT1={difference_1_K:.4f} K, DT2={difference_2_K:.4f} K."
        )
    if math.isclose(difference_1_K, difference_2_K, abs_tol=1.0e-10):
        return 0.5 * (difference_1_K + difference_2_K)
    return (difference_1_K - difference_2_K) / math.log(
        difference_1_K / difference_2_K
    )


def size_heat_exchanger(
    duty_kW: float,
    terminal_difference_1_K: float,
    terminal_difference_2_K: float,
    correction_factor: float = 1.0,
) -> HeatExchangerSizingResult:
    """Retorna o UA necessário; o UA ainda não limita a capacidade do ciclo."""
    if duty_kW <= 0.0:
        raise ValueError("A carga do trocador deve ser positiva.")
    if not 0.0 < correction_factor <= 1.0:
        raise ValueError("O fator de correção deve estar entre zero e um.")
    lmtd_K = logarithmic_mean_temperature_difference_K(
        terminal_difference_1_K,
        terminal_difference_2_K,
    )
    return HeatExchangerSizingResult(
        duty_kW=duty_kW,
        terminal_temperature_difference_1_K=terminal_difference_1_K,
        terminal_temperature_difference_2_K=terminal_difference_2_K,
        lmtd_K=lmtd_K,
        correction_factor=correction_factor,
        ua_kW_K=duty_kW / (correction_factor * lmtd_K),
    )
