"""Thermodynamic and recovery-bookkeeping tests for the generic expander."""

from dataclasses import replace
import unittest

from hthp.components.expander import AdiabaticExpander
from hthp.components.expansion_valve import ExpansionValve
from hthp.cycles.expander_cycle import ExpanderCycle, ExpanderCycleConfig
from hthp.cycles.simple_cycle import SimpleCycleConfig, SimpleVaporCompressionCycle
from hthp.heat_sources.base import HeatSourceEvaluation
from hthp.heat_sources.fixed_temperature import FixedTemperatureHeatSource


class ExpanderCycleTests(unittest.TestCase):
    def config(self, fluid="R1233zd(E)", **kwargs):
        return replace(ExpanderCycleConfig(
            refrigerant=fluid,
            heat_source=FixedTemperatureHeatSource(45 if fluid == "R1233zd(E)" else 20),
            condensation_temperature_C=125 if fluid == "R1233zd(E)" else 50,
            heating_capacity_kW=1.0, subcooling_K=0.01,
        ), **kwargs)

    def conventional(self, config):
        values = {name: getattr(config, name) for name in SimpleCycleConfig.__dataclass_fields__}
        return SimpleVaporCompressionCycle(SimpleCycleConfig(**values)).solve()

    def test_zero_efficiency_reproduces_valve_for_both_fluids(self):
        for fluid in ("R32", "R1233zd(E)"):
            with self.subTest(fluid=fluid):
                c = self.config(fluid, expander_isentropic_efficiency=0,
                                external_subcooling_specific_heat_kJ_kg=5)
                r, base = ExpanderCycle(c).solve(), self.conventional(c)
                self.assertEqual(r.states, base.states)
                for name in ("refrigerant_mass_flow_kg_s", "evaporator_heat_kW",
                             "condenser_heat_kW", "external_subcooler_heat_kW",
                             "compressor_shaft_power_kW", "compressor_electrical_power_kW",
                             "motor_loss_kW", "heating_COP", "energy_balance_error_kW"):
                    self.assertAlmostEqual(getattr(r, name), getattr(base, name), places=12)
                self.assertEqual(r.expander_shaft_power_kW, 0)
                self.assertEqual(r.recovered_power_kW, 0)
                self.assertEqual(r.net_electrical_power_kW, base.compressor_electrical_power_kW)

    def test_work_recovery_changes_state_and_evaporator_duty(self):
        for fluid in ("R32", "R1233zd(E)"):
            with self.subTest(fluid=fluid):
                c = self.config(fluid)
                r, base = ExpanderCycle(c).solve(), self.conventional(c)
                self.assertLess(r.states[4].enthalpy_kJ_kg, base.states[4].enthalpy_kJ_kg)
                self.assertGreater(r.evaporator_heat_kW, base.evaporator_heat_kW)
                self.assertAlmostEqual(r.evaporator_heat_kW-base.evaporator_heat_kW,
                                       r.expander_shaft_power_kW)
                self.assertEqual(r.states[1], base.states[1])
                self.assertEqual(r.states[2], base.states[2])
                self.assertEqual(r.refrigerant_mass_flow_kg_s, base.refrigerant_mass_flow_kg_s)
                self.assertGreater(r.heating_COP, base.heating_COP)
                self.assertLess(r.net_shaft_power_kW, r.compressor_shaft_power_kW)
                self.assertGreater(r.expander_shaft_power_kW, 0)
                self.assertLess(abs(r.energy_balance_error_kW), 1e-10)
                self.assertLess(abs(r.system_energy_balance_error_kW), 1e-10)
                self.assertAlmostEqual(r.heating_COP,
                                       (r.condenser_heat_kW+r.external_subcooler_heat_kW)
                                       / r.net_electrical_power_kW)

    def test_efficiency_definition_and_entropy_limits(self):
        for fluid in ("R32", "R1233zd(E)"):
            base = self.conventional(self.config(fluid))
            inlet, pout = base.states["3E"], base.states[1].pressure_Pa
            valve = ExpansionValve().expand(fluid, inlet, pout)
            for eta in (0, 0.25, 0.5, 1):
                with self.subTest(fluid=fluid, eta=eta):
                    r = AdiabaticExpander(eta).expand(fluid, inlet, pout)
                    self.assertAlmostEqual(r.specific_shaft_work_kJ_kg,
                                           inlet.enthalpy_kJ_kg-r.outlet.enthalpy_kJ_kg)
                    self.assertAlmostEqual(r.specific_shaft_work_kJ_kg,
                                           eta*(inlet.enthalpy_kJ_kg-r.isentropic_outlet_enthalpy_kJ_kg))
                    self.assertGreaterEqual(r.outlet.entropy_kJ_kgK, inlet.entropy_kJ_kgK-1e-8)
                    self.assertLessEqual(r.outlet.enthalpy_kJ_kg, valve.enthalpy_kJ_kg)
                    if eta == 0:
                        self.assertEqual(r.outlet, valve)
                    if eta == 1:
                        self.assertAlmostEqual(r.outlet.entropy_kJ_kgK,
                                               inlet.entropy_kJ_kgK, places=7)

    def test_partial_recovery_loss_is_not_useful_heat(self):
        full = ExpanderCycle(self.config()).solve()
        r = ExpanderCycle(self.config(expander_recovery_efficiency=0.6)).solve()
        self.assertEqual(full.states, r.states)
        self.assertAlmostEqual(r.recovered_power_kW, 0.6*r.expander_shaft_power_kW)
        self.assertAlmostEqual(r.unrecovered_expander_power_kW, 0.4*r.expander_shaft_power_kW)
        self.assertAlmostEqual(r.net_shaft_power_kW, r.compressor_shaft_power_kW-r.recovered_power_kW)
        self.assertLess(r.heating_COP, full.heating_COP)
        self.assertLess(abs(r.system_energy_balance_error_kW), 1e-10)

    def test_zero_recovery_does_not_invent_a_cop_gain(self):
        c = self.config(expander_recovery_efficiency=0)
        r, base = ExpanderCycle(c).solve(), self.conventional(c)
        self.assertGreater(r.expander_shaft_power_kW, 0)
        self.assertGreater(r.evaporator_heat_kW, base.evaporator_heat_kW)
        self.assertEqual(r.recovered_power_kW, 0)
        self.assertEqual(r.net_shaft_power_kW, base.compressor_shaft_power_kW)
        self.assertEqual(r.heating_COP, base.heating_COP)
        self.assertLess(abs(r.system_energy_balance_error_kW), 1e-10)

    def test_saturated_condenser_outlet_and_capacity_scaling(self):
        a = ExpanderCycle(self.config(subcooling_K=0)).solve()
        b = ExpanderCycle(self.config(subcooling_K=0, heating_capacity_kW=4)).solve()
        self.assertEqual(a.states[3].quality, 0)
        self.assertAlmostEqual(b.refrigerant_mass_flow_kg_s, 4*a.refrigerant_mass_flow_kg_s)
        self.assertAlmostEqual(a.heating_COP, b.heating_COP)
        self.assertAlmostEqual(b.expander_shaft_power_kW, 4*a.expander_shaft_power_kW)

    def test_source_is_rechecked_with_new_evaporator_duty(self):
        required = ExpanderCycle(self.config()).solve().evaporator_heat_kW

        class LimitedSource:
            def evaporation_temperature_C(self):
                return 45

            def evaluate(self, heat_extracted_kW):
                return HeatSourceEvaluation("limited", 45, heat_extracted_kW,
                                            heat_extracted_kW <= 0.99*required,
                                            maximum_heat_kW=0.99*required)

        self.conventional(self.config(heat_source=LimitedSource()))
        with self.assertRaisesRegex(ValueError, "fonte"):
            ExpanderCycle(self.config(heat_source=LimitedSource())).solve()

    def test_invalid_efficiencies_and_pressures(self):
        for eta in (-0.1, 1.01, float("nan"), float("inf")):
            with self.subTest(eta=eta):
                with self.assertRaises(ValueError):
                    AdiabaticExpander(eta)
                with self.assertRaises(ValueError):
                    ExpanderCycle(self.config(expander_recovery_efficiency=eta)).solve()
        inlet = self.conventional(self.config()).states["3E"]
        for pressure in (0, -1, inlet.pressure_Pa, inlet.pressure_Pa*1.1, float("nan")):
            with self.subTest(pressure=pressure), self.assertRaises(ValueError):
                AdiabaticExpander().expand("R1233zd(E)", inlet, pressure)

    def test_invalid_cycle_conditions(self):
        for kwargs in (dict(heating_capacity_kW=0), dict(heating_capacity_kW=float("nan")),
                       dict(superheat_K=0), dict(subcooling_K=-1),
                       dict(external_subcooling_specific_heat_kJ_kg=-1),
                       dict(condensation_temperature_C=200), dict(condensation_temperature_C=40)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ExpanderCycle(self.config(**kwargs)).solve()


if __name__ == "__main__":
    unittest.main()
