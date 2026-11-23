"""Within-circuit expansion recovery with flash/economizer vapor injection."""

from dataclasses import replace
import unittest

from hthp.cycles.flash_tank_cycle import FlashTankCycle, FlashTankCycleConfig
from hthp.cycles.economizer_cycle import EconomizerCycle, EconomizerCycleConfig
from hthp.heat_sources.fixed_temperature import FixedTemperatureHeatSource


class InjectionExpanderTests(unittest.TestCase):
    families = (
        (FlashTankCycle, FlashTankCycleConfig, ("before", "after", "both")),
        (EconomizerCycle, EconomizerCycleConfig, ("main", "injection", "both")),
    )

    def config(self, config_class, fluid="R1233zd(E)", **kwargs):
        return replace(config_class(
            refrigerant=fluid,
            heat_source=FixedTemperatureHeatSource(
                45 if fluid == "R1233zd(E)" else 20),
            condensation_temperature_C=125 if fluid == "R1233zd(E)" else 50,
            heating_capacity_kW=1.0, subcooling_K=0.01,
        ), **kwargs)

    def test_zero_expander_efficiency_recovers_each_valve_model(self):
        for cycle_class, config_class, modes in self.families:
            for fluid in ("R32", "R1233zd(E)"):
                c = self.config(config_class, fluid,
                                external_subcooling_specific_heat_kJ_kg=5.0)
                base = cycle_class(c).solve()
                for mode in modes:
                    with self.subTest(cycle=cycle_class.__name__, fluid=fluid, mode=mode):
                        result = cycle_class(replace(
                            c, expansion_mode=mode,
                            expander_isentropic_efficiency=0.0)).solve()
                        self.assertEqual(result.states, base.states)
                        for key in ("heating_COP", "total_refrigerant_mass_flow_kg_s",
                                    "injected_vapor_mass_flow_kg_s", "evaporator_heat_kW",
                                    "total_shaft_power_kW", "total_electrical_power_kW",
                                    "motor_loss_kW"):
                            self.assertAlmostEqual(getattr(result, key), getattr(base, key), places=12)
                        self.assertEqual(result.expander_shaft_power_kW, 0.0)
                        self.assertEqual(result.recovered_power_kW, 0.0)
                        self.assertAlmostEqual(result.net_shaft_power_kW,
                                               base.total_shaft_power_kW)

    def test_all_modes_close_refrigerant_and_system_energy(self):
        for cycle_class, config_class, modes in self.families:
            for fluid in ("R32", "R1233zd(E)"):
                for mode in ("valves", *modes):
                    with self.subTest(cycle=cycle_class.__name__, fluid=fluid, mode=mode):
                        c = self.config(config_class, fluid, expansion_mode=mode,
                                        external_subcooling_specific_heat_kJ_kg=5.0,
                                        expander_recovery_efficiency=0.6)
                        r = cycle_class(c).solve()
                        useful = r.condenser_heat_kW + r.external_subcooler_heat_kW
                        self.assertLess(abs(r.energy_balance_error_kW), 1e-10)
                        self.assertLess(abs(r.system_energy_balance_error_kW), 1e-10)
                        self.assertAlmostEqual(
                            useful, r.evaporator_heat_kW + r.total_shaft_power_kW
                            - r.expander_shaft_power_kW, places=10)
                        self.assertAlmostEqual(r.recovered_power_kW,
                                               0.6*r.expander_shaft_power_kW)
                        self.assertAlmostEqual(r.unrecovered_expander_power_kW,
                                               0.4*r.expander_shaft_power_kW)
                        self.assertAlmostEqual(r.net_shaft_power_kW,
                                               r.total_shaft_power_kW-r.recovered_power_kW)
                        self.assertAlmostEqual(r.total_electrical_power_kW,
                                               r.net_shaft_power_kW/c.motor_efficiency)
                        self.assertEqual(r.total_electrical_power_kW,
                                         r.net_electrical_power_kW)
                        self.assertAlmostEqual(r.heating_COP,
                                               useful/r.net_electrical_power_kW)
                        self.assertAlmostEqual(r.total_refrigerant_mass_flow_kg_s,
                                               r.evaporator_mass_flow_kg_s
                                               + r.injected_vapor_mass_flow_kg_s)
                        if mode != "valves":
                            self.assertGreater(r.expander_shaft_power_kW, 0.0)

    def test_work_uses_the_flow_of_each_branch(self):
        for cycle_class, config_class, _ in self.families:
            for fluid in ("R32", "R1233zd(E)"):
                with self.subTest(cycle=cycle_class.__name__, fluid=fluid):
                    r = cycle_class(self.config(config_class, fluid,
                                                expansion_mode="both")).solve()
                    if cycle_class is FlashTankCycle:
                        expected = (
                            r.total_refrigerant_mass_flow_kg_s
                            * r.expanders["before"].specific_shaft_work_kJ_kg
                            + r.evaporator_mass_flow_kg_s
                            * r.expanders["after"].specific_shaft_work_kJ_kg)
                    else:
                        expected = (
                            r.evaporator_mass_flow_kg_s
                            * r.expanders["main"].specific_shaft_work_kJ_kg
                            + r.injected_vapor_mass_flow_kg_s
                            * r.expanders["injection"].specific_shaft_work_kJ_kg)
                    self.assertAlmostEqual(r.expander_shaft_power_kW, expected, places=12)

    def test_flash_upper_expander_recalculates_vapor_fraction(self):
        for fluid in ("R32", "R1233zd(E)"):
            c = self.config(FlashTankCycleConfig, fluid)
            base = FlashTankCycle(c).solve()
            before = FlashTankCycle(replace(c, expansion_mode="before")).solve()
            after = FlashTankCycle(replace(c, expansion_mode="after")).solve()
            self.assertLess(before.flash_vapor_fraction, base.flash_vapor_fraction)
            self.assertLess(before.states["6"].enthalpy_kJ_kg,
                            base.states["6"].enthalpy_kJ_kg)
            self.assertEqual(after.flash_vapor_fraction, base.flash_vapor_fraction)
            self.assertLess(after.states["7"].enthalpy_kJ_kg,
                            base.states["7"].enthalpy_kJ_kg)
            self.assertAlmostEqual(after.evaporator_heat_kW-base.evaporator_heat_kW,
                                   after.expander_shaft_power_kW)

    def test_economizer_injection_expander_recalculates_split(self):
        for fluid in ("R32", "R1233zd(E)"):
            c = self.config(EconomizerCycleConfig, fluid)
            base = EconomizerCycle(c).solve()
            inj = EconomizerCycle(replace(c, expansion_mode="injection")).solve()
            main = EconomizerCycle(replace(c, expansion_mode="main")).solve()
            self.assertLess(inj.injection_mass_fraction, base.injection_mass_fraction)
            self.assertEqual(main.injection_mass_fraction, base.injection_mass_fraction)
            self.assertLess(inj.states["8"].enthalpy_kJ_kg,
                            base.states["8"].enthalpy_kJ_kg)
            self.assertLess(main.states["7"].enthalpy_kJ_kg,
                            base.states["7"].enthalpy_kJ_kg)
            self.assertLess(abs(inj.economizer_balance_error_kW), 1e-12)

    def test_recovery_changes_electrical_draw_not_refrigerant_states(self):
        for cycle_class, config_class, modes in self.families:
            c = self.config(config_class, expansion_mode=modes[0])
            full = cycle_class(c).solve()
            partial = cycle_class(replace(c, expander_recovery_efficiency=0.4)).solve()
            zero = cycle_class(replace(c, expander_recovery_efficiency=0.0)).solve()
            self.assertEqual(full.states, partial.states)
            self.assertEqual(full.states, zero.states)
            self.assertGreater(full.heating_COP, partial.heating_COP)
            self.assertGreater(partial.heating_COP, zero.heating_COP)
            self.assertEqual(zero.net_shaft_power_kW, zero.total_shaft_power_kW)
            self.assertGreater(zero.unrecovered_expander_power_kW, 0.0)
            self.assertLess(abs(zero.system_energy_balance_error_kW), 1e-10)

    def test_capacity_scales_flow_and_recovered_power(self):
        for cycle_class, config_class, _ in self.families:
            c = self.config(config_class, expansion_mode="both")
            one = cycle_class(c).solve()
            four = cycle_class(replace(c, heating_capacity_kW=4.0)).solve()
            self.assertAlmostEqual(four.expander_shaft_power_kW,
                                   4*one.expander_shaft_power_kW)
            self.assertAlmostEqual(four.net_electrical_power_kW,
                                   4*one.net_electrical_power_kW)
            self.assertAlmostEqual(one.heating_COP, four.heating_COP)

    def test_invalid_modes_and_efficiencies_are_rejected(self):
        for cycle_class, config_class, _ in self.families:
            with self.assertRaisesRegex(ValueError, "Modo"):
                cycle_class(self.config(config_class, expansion_mode="unknown")).solve()
            for name in ("expander_isentropic_efficiency", "expander_recovery_efficiency"):
                for value in (-0.1, 1.01, float("nan"), float("inf")):
                    with self.subTest(cycle=cycle_class.__name__, name=name, value=value):
                        with self.assertRaises(ValueError):
                            cycle_class(self.config(config_class, **{name: value})).solve()


if __name__ == "__main__":
    unittest.main()
