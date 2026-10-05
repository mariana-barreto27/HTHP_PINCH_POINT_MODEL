"""Separador adiabático de líquido e vapor na pressão intermediária."""

from dataclasses import dataclass

from hthp.thermo.state import ThermodynamicState


@dataclass(frozen=True)
class FlashTankResult:
    inlet: ThermodynamicState
    saturated_liquid: ThermodynamicState
    saturated_vapor: ThermodynamicState
    vapor_mass_fraction: float


@dataclass(frozen=True)
class FlashTank:
    def separate(
        self,
        refrigerant: str,
        inlet: ThermodynamicState,
    ) -> FlashTankResult:
        liquid = ThermodynamicState.from_pressure_quality(
            refrigerant,
            inlet.pressure_Pa,
            0.0,
        )
        vapor = ThermodynamicState.from_pressure_quality(
            refrigerant,
            inlet.pressure_Pa,
            1.0,
        )
        latent_heat = vapor.enthalpy_kJ_kg - liquid.enthalpy_kJ_kg
        if latent_heat <= 0.0:
            raise ValueError("Não há região bifásica válida na pressão intermediária.")

        vapor_fraction = (
            inlet.enthalpy_kJ_kg - liquid.enthalpy_kJ_kg
        ) / latent_heat
        if not 0.0 < vapor_fraction < 1.0:
            raise ValueError(
                "A entrada do flash tank precisa estar na região bifásica."
            )
        return FlashTankResult(
            inlet=inlet,
            saturated_liquid=liquid,
            saturated_vapor=vapor,
            vapor_mass_fraction=vapor_fraction,
        )

