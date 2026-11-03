"""Heat-pump expander replacing the valve, with explicit shaft recovery.

Flow: compressor -> condenser -> optional external water subcooler -> expander
-> evaporator. Expansion lowers evaporator-inlet enthalpy and changes its heat
uptake; the source must be evaluated with the new duty.

Recovered power assists the compressor shaft before the motor. Defaults 0.50
isentropic efficiency and 1.0 recovery efficiency are study assumptions; the
latter is ideal mechanical utilization, not experimental validation. Unrecovered
expander power is rejected externally, not counted as useful heat or source heat.
"""

from dataclasses import dataclass
import math

from hthp.components.compressor import Compressor
from hthp.components.condenser import Condenser
from hthp.components.evaporator import Evaporator
from hthp.components.expander import AdiabaticExpander, ExpanderResult
from hthp.cycles.simple_cycle import SimpleCycleConfig, SimpleCycleResult
from hthp.thermo.properties import critical_temperature_C, saturation_pressure_Pa
from hthp.thermo.state import ThermodynamicState


@dataclass(frozen=True)
class ExpanderCycleConfig(SimpleCycleConfig):
    expander_isentropic_efficiency: float = 0.50
    expander_recovery_efficiency: float = 1.0


@dataclass(frozen=True)
class ExpanderCycleResult(SimpleCycleResult):
    config: ExpanderCycleConfig
    expander: ExpanderResult
    expander_shaft_power_kW: float
    recovered_power_kW: float
    unrecovered_expander_power_kW: float
    net_shaft_power_kW: float
    net_electrical_power_kW: float
    system_energy_balance_error_kW: float


class ExpanderCycle:
    def __init__(self, config: ExpanderCycleConfig) -> None:
        self.config = config

    def solve(self) -> ExpanderCycleResult:
        c = self.config
        tev = c.heat_source.evaporation_temperature_C()
        self._validate(tev)
        expander = AdiabaticExpander(c.expander_isentropic_efficiency)
        s1 = Evaporator(tev, c.superheat_K).outlet_state(c.refrigerant)
        if c.subcooling_K == 0.0:
            s3 = ThermodynamicState.from_pressure_quality(
                c.refrigerant,
                saturation_pressure_Pa(c.refrigerant, c.condensation_temperature_C), 0,
            )
        else:
            s3 = Condenser(c.condensation_temperature_C, c.subcooling_K).outlet_state(c.refrigerant)
        s3e = ThermodynamicState.from_pressure_enthalpy(
            c.refrigerant, s3.pressure_Pa,
            s3.enthalpy_kJ_kg - c.external_subcooling_specific_heat_kJ_kg,
        )
        comp = Compressor(c.compressor_isentropic_efficiency, c.motor_efficiency,
                          c.compressor_efficiency_model).compress(
                              c.refrigerant, s1, s3.pressure_Pa)
        s2 = comp.outlet
        expansion = expander.expand(c.refrigerant, s3e, s1.pressure_Pa)
        s4 = expansion.outlet
        qcond = s2.enthalpy_kJ_kg - s3.enthalpy_kJ_kg
        qevap = s1.enthalpy_kJ_kg - s4.enthalpy_kJ_kg
        if not math.isfinite(qcond) or qcond <= 0.0:
            raise ValueError("The refrigerant cannot reject heat in this condenser.")
        if not math.isfinite(qevap) or qevap <= 0.0:
            raise ValueError("The refrigerant cannot absorb heat in this evaporator.")
        mass = c.heating_capacity_kW / qcond
        qsc = mass * c.external_subcooling_specific_heat_kJ_kg
        useful = c.heating_capacity_kW + qsc
        qev = mass * qevap
        wc = mass * comp.specific_shaft_work_kJ_kg
        wt = mass * expansion.specific_shaft_work_kJ_kg
        recovered = c.expander_recovery_efficiency * wt
        rejected = wt - recovered
        net = wc - recovered
        if not math.isfinite(net) or net <= 0.0:
            raise ValueError("The heat pump requires positive net compressor-shaft power.")
        gross_electric = mass * comp.specific_electrical_work_kJ_kg
        net_electric = net / c.motor_efficiency
        source = c.heat_source.evaluate(qev)
        if not source.feasible:
            raise ValueError(
                "A fonte de processo não fornece o calor necessário com expansor: "
                f"necessário={qev:.2f} kW, máximo={source.maximum_heat_kW} kW."
            )
        # Refrigerant control volume: Quse = Qev + Wcomp - Wexp.
        residual = useful - qev - wc + wt
        # System with shaft-recovery losses: Quse + loss = Qev + Wnet.
        system_residual = useful + rejected - qev - net
        return ExpanderCycleResult(
            config=c, evaporation_temperature_C=tev,
            states={1: s1, 2: s2, 3: s3, "3E": s3e, 4: s4},
            refrigerant_mass_flow_kg_s=mass, evaporator_heat_kW=qev,
            condenser_heat_kW=c.heating_capacity_kW,
            external_subcooler_heat_kW=qsc,
            compressor_shaft_power_kW=wc,
            # Gross electrical draw before any expander shaft assistance.
            compressor_electrical_power_kW=gross_electric,
            compressor_isentropic_efficiency=comp.isentropic_efficiency,
            compressor_raw_isentropic_efficiency=comp.raw_isentropic_efficiency,
            compressor_efficiency_limit_status=comp.efficiency_limit_status,
            motor_loss_kW=net_electric - net,
            heating_COP=useful / net_electric,
            pressure_ratio=s3.pressure_Pa / s1.pressure_Pa,
            energy_balance_error_kW=residual, heat_source=source,
            expander=expansion, expander_shaft_power_kW=wt,
            recovered_power_kW=recovered, unrecovered_expander_power_kW=rejected,
            net_shaft_power_kW=net, net_electrical_power_kW=net_electric,
            system_energy_balance_error_kW=system_residual,
        )

    def _validate(self, tev: float) -> None:
        c = self.config
        values = (tev, c.condensation_temperature_C, c.heating_capacity_kW,
                  c.superheat_K, c.subcooling_K,
                  c.external_subcooling_specific_heat_kJ_kg,
                  c.expander_recovery_efficiency)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Expander-cycle inputs must be finite.")
        if not 0.0 <= c.expander_recovery_efficiency <= 1.0:
            raise ValueError("Expander recovery efficiency must be in [0, 1].")
        if c.heating_capacity_kW <= 0.0 or c.superheat_K <= 0.0:
            raise ValueError("Heating capacity and suction superheat must be positive.")
        if c.subcooling_K < 0.0 or c.external_subcooling_specific_heat_kJ_kg < 0.0:
            raise ValueError("Subcooling and external subcooler duty cannot be negative.")
        if not tev < c.condensation_temperature_C:
            raise ValueError("Evaporation must be colder than condensation.")
        if c.condensation_temperature_C >= critical_temperature_C(c.refrigerant):
            raise ValueError("This expander heat-pump model requires subcritical condensation.")
