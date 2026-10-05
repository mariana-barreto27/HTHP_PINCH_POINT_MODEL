"""Compressor adiabático com eficiências isentrópica e elétrica."""

from dataclasses import dataclass

from hthp.components.compressor_performance import IsentropicEfficiencyModel
from hthp.thermo.properties import props_si_cached
from hthp.thermo.state import ThermodynamicState


@dataclass(frozen=True)
class CompressorResult:
    outlet: ThermodynamicState
    isentropic_outlet_enthalpy_kJ_kg: float
    specific_shaft_work_kJ_kg: float
    specific_electrical_work_kJ_kg: float
    isentropic_efficiency: float
    raw_isentropic_efficiency: float
    efficiency_limit_status: str
    pressure_ratio: float

    @property
    def efficiency_was_limited(self) -> bool:
        return self.efficiency_limit_status != "none"


@dataclass(frozen=True)
class Compressor:
    isentropic_efficiency: float
    motor_efficiency: float
    efficiency_model: IsentropicEfficiencyModel | None = None

    def __post_init__(self) -> None:
        if not 0.0 < self.isentropic_efficiency <= 1.0:
            raise ValueError("A eficiência isentrópica deve estar entre 0 e 1.")
        if not 0.0 < self.motor_efficiency <= 1.0:
            raise ValueError("A eficiência do motor deve estar entre 0 e 1.")

    def compress(
        self,
        refrigerant: str,
        inlet: ThermodynamicState,
        outlet_pressure_Pa: float,
    ) -> CompressorResult:
        if outlet_pressure_Pa <= inlet.pressure_Pa:
            raise ValueError("A pressão de descarga deve superar a pressão de sucção.")

        pressure_ratio = outlet_pressure_Pa / inlet.pressure_Pa
        if self.efficiency_model is None:
            isentropic_efficiency = self.isentropic_efficiency
            raw_isentropic_efficiency = self.isentropic_efficiency
            efficiency_limit_status = "none"
        else:
            efficiency_evaluation = self.efficiency_model.evaluate(
                pressure_ratio
            )
            isentropic_efficiency = efficiency_evaluation.efficiency
            raw_isentropic_efficiency = (
                efficiency_evaluation.raw_efficiency
            )
            efficiency_limit_status = efficiency_evaluation.limit_status
        h2s_kJ_kg = props_si_cached(
            "H",
            "P",
            outlet_pressure_Pa,
            "S",
            inlet.entropy_kJ_kgK * 1000.0,
            refrigerant,
        ) / 1000.0
        specific_shaft_work = (
            h2s_kJ_kg - inlet.enthalpy_kJ_kg
        ) / isentropic_efficiency
        outlet_enthalpy = inlet.enthalpy_kJ_kg + specific_shaft_work
        outlet = ThermodynamicState.from_pressure_enthalpy(
            refrigerant,
            outlet_pressure_Pa,
            outlet_enthalpy,
        )

        return CompressorResult(
            outlet=outlet,
            isentropic_outlet_enthalpy_kJ_kg=h2s_kJ_kg,
            specific_shaft_work_kJ_kg=specific_shaft_work,
            specific_electrical_work_kJ_kg=(
                specific_shaft_work / self.motor_efficiency
            ),
            isentropic_efficiency=isentropic_efficiency,
            raw_isentropic_efficiency=raw_isentropic_efficiency,
            efficiency_limit_status=efficiency_limit_status,
            pressure_ratio=pressure_ratio,
        )
