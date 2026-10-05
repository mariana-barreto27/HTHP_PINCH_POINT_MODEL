"""Correlações opcionais de eficiência e dimensionamento do compressor."""

from dataclasses import dataclass
from typing import Literal, Protocol

from hthp.thermo.properties import props_si_cached
from hthp.thermo.state import ThermodynamicState


class IsentropicEfficiencyModel(Protocol):
    def evaluate(self, pressure_ratio: float) -> "IsentropicEfficiencyEvaluation":
        """Avalia a curva e informa se um limite foi acionado."""

    def efficiency(self, pressure_ratio: float) -> float:
        """Retorna a eficiência isentrópica para uma razão de pressão."""


@dataclass(frozen=True)
class IsentropicEfficiencyEvaluation:
    pressure_ratio: float
    raw_efficiency: float
    efficiency: float
    limit_status: Literal["none", "minimum", "maximum"]

    @property
    def was_limited(self) -> bool:
        return self.limit_status != "none"


def _bounded_efficiency_evaluation(
    pressure_ratio: float,
    raw_efficiency: float,
    minimum_efficiency: float,
    maximum_efficiency: float,
) -> IsentropicEfficiencyEvaluation:
    if raw_efficiency < minimum_efficiency:
        efficiency = minimum_efficiency
        limit_status: Literal["none", "minimum", "maximum"] = "minimum"
    elif raw_efficiency > maximum_efficiency:
        efficiency = maximum_efficiency
        limit_status = "maximum"
    else:
        efficiency = raw_efficiency
        limit_status = "none"
    return IsentropicEfficiencyEvaluation(
        pressure_ratio=pressure_ratio,
        raw_efficiency=raw_efficiency,
        efficiency=efficiency,
        limit_status=limit_status,
    )


@dataclass(frozen=True)
class LinearPressureRatioEfficiency:
    """Modelo eta_is = eta_RP1 + slope*(RP - 1), com limites físicos."""

    efficiency_at_unit_pressure_ratio: float = 0.80
    slope_per_pressure_ratio: float = -0.05
    minimum_efficiency: float = 0.40
    maximum_efficiency: float = 0.90

    def __post_init__(self) -> None:
        if not 0.0 < self.minimum_efficiency <= self.maximum_efficiency <= 1.0:
            raise ValueError("Os limites da eficiência isentrópica são inválidos.")
        if self.slope_per_pressure_ratio > 0.0:
            raise ValueError("A curva linear deve ser constante ou decrescente.")

    def evaluate(self, pressure_ratio: float) -> IsentropicEfficiencyEvaluation:
        if pressure_ratio < 1.0:
            raise ValueError("A razão de pressão deve ser maior ou igual a um.")
        raw = self.efficiency_at_unit_pressure_ratio + (
            self.slope_per_pressure_ratio * (pressure_ratio - 1.0)
        )
        return _bounded_efficiency_evaluation(
            pressure_ratio,
            raw,
            self.minimum_efficiency,
            self.maximum_efficiency,
        )

    def efficiency(self, pressure_ratio: float) -> float:
        return self.evaluate(pressure_ratio).efficiency


@dataclass(frozen=True)
class QuadraticPressureRatioEfficiency:
    """Modelo eta_is = a + b*RP + c*RP², limitado a uma faixa física."""

    a: float
    b: float
    c: float
    minimum_efficiency: float = 0.40
    maximum_efficiency: float = 0.90

    def __post_init__(self) -> None:
        if not 0.0 < self.minimum_efficiency <= self.maximum_efficiency <= 1.0:
            raise ValueError("Os limites da eficiência isentrópica são inválidos.")

    def evaluate(self, pressure_ratio: float) -> IsentropicEfficiencyEvaluation:
        if pressure_ratio <= 1.0:
            raise ValueError("A razão de pressão deve ser maior que um.")
        raw = self.a + self.b * pressure_ratio + self.c * pressure_ratio**2
        return _bounded_efficiency_evaluation(
            pressure_ratio,
            raw,
            self.minimum_efficiency,
            self.maximum_efficiency,
        )

    def efficiency(self, pressure_ratio: float) -> float:
        return self.evaluate(pressure_ratio).efficiency


@dataclass(frozen=True)
class VolumetricEfficiencyModel:
    """Eficiência volumétrica baseada no volume de folga do compressor."""

    clearance_fraction: float = 0.02

    def __post_init__(self) -> None:
        if not 0.0 <= self.clearance_fraction < 1.0:
            raise ValueError("A fração de folga deve ficar entre zero e um.")

    def efficiency(self, pressure_ratio: float, heat_capacity_ratio: float) -> float:
        if pressure_ratio <= 1.0 or heat_capacity_ratio <= 1.0:
            raise ValueError("RP e k devem ser maiores que um.")
        value = 1.0 - self.clearance_fraction * (
            pressure_ratio ** (1.0 / heat_capacity_ratio) - 1.0
        )
        if not 0.0 < value <= 1.0:
            raise ValueError(
                f"Eficiência volumétrica não física: eta_v={value:.4f}."
            )
        return value


@dataclass(frozen=True)
class CompressorHardwareConfig:
    mode: Literal["size_displacement", "required_speed"]
    clearance_fraction: float = 0.02
    fixed_speed_Hz: float | None = None
    fixed_displacement_m3_rev: float | None = None
    minimum_speed_Hz: float | None = None
    maximum_speed_Hz: float | None = None

    def __post_init__(self) -> None:
        if self.mode == "size_displacement":
            if self.fixed_speed_Hz is None or self.fixed_speed_Hz <= 0.0:
                raise ValueError("O modo de capacidade exige rotação positiva.")
        elif self.mode == "required_speed":
            if (
                self.fixed_displacement_m3_rev is None
                or self.fixed_displacement_m3_rev <= 0.0
            ):
                raise ValueError(
                    "O modo de deslocamento exige volume deslocado positivo."
                )
        else:
            raise ValueError(f"Modo de compressor desconhecido: {self.mode}.")
        if (
            self.minimum_speed_Hz is not None
            and self.maximum_speed_Hz is not None
            and self.maximum_speed_Hz < self.minimum_speed_Hz
        ):
            raise ValueError("A faixa de rotação do compressor é inválida.")


@dataclass(frozen=True)
class CompressorHardwareResult:
    mass_flow_kg_s: float
    pressure_ratio: float
    heat_capacity_ratio: float
    suction_specific_volume_m3_kg: float
    volumetric_efficiency: float
    required_speed_Hz: float
    required_speed_rpm: float
    required_displacement_m3_rev: float
    speed_feasible: bool


def evaluate_compressor_hardware(
    refrigerant: str,
    suction_state: ThermodynamicState,
    discharge_pressure_Pa: float,
    mass_flow_kg_s: float,
    config: CompressorHardwareConfig,
) -> CompressorHardwareResult:
    """Dimensiona deslocamento ou rotação usando a vazão já resolvida."""
    if mass_flow_kg_s <= 0.0:
        raise ValueError("A vazão do compressor deve ser positiva.")
    pressure_ratio = discharge_pressure_Pa / suction_state.pressure_Pa
    cp = props_si_cached(
        "CPMASS",
        "P",
        suction_state.pressure_Pa,
        "H",
        suction_state.enthalpy_kJ_kg * 1000.0,
        refrigerant,
    )
    cv = props_si_cached(
        "CVMASS",
        "P",
        suction_state.pressure_Pa,
        "H",
        suction_state.enthalpy_kJ_kg * 1000.0,
        refrigerant,
    )
    density = props_si_cached(
        "DMASS",
        "P",
        suction_state.pressure_Pa,
        "H",
        suction_state.enthalpy_kJ_kg * 1000.0,
        refrigerant,
    )
    heat_capacity_ratio = cp / cv
    specific_volume = 1.0 / density
    volumetric_efficiency = VolumetricEfficiencyModel(
        config.clearance_fraction
    ).efficiency(pressure_ratio, heat_capacity_ratio)

    if config.mode == "size_displacement":
        speed_Hz = float(config.fixed_speed_Hz)
        displacement = (
            mass_flow_kg_s
            * specific_volume
            / (volumetric_efficiency * speed_Hz)
        )
    else:
        displacement = float(config.fixed_displacement_m3_rev)
        speed_Hz = (
            mass_flow_kg_s
            * specific_volume
            / (volumetric_efficiency * displacement)
        )
    speed_feasible = True
    if config.minimum_speed_Hz is not None:
        speed_feasible = speed_feasible and speed_Hz >= config.minimum_speed_Hz
    if config.maximum_speed_Hz is not None:
        speed_feasible = speed_feasible and speed_Hz <= config.maximum_speed_Hz
    return CompressorHardwareResult(
        mass_flow_kg_s=mass_flow_kg_s,
        pressure_ratio=pressure_ratio,
        heat_capacity_ratio=heat_capacity_ratio,
        suction_specific_volume_m3_kg=specific_volume,
        volumetric_efficiency=volumetric_efficiency,
        required_speed_Hz=speed_Hz,
        required_speed_rpm=speed_Hz * 60.0,
        required_displacement_m3_rev=displacement,
        speed_feasible=speed_feasible,
    )

