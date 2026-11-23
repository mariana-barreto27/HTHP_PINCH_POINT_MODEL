"""Within-circuit ejector + liquid-branch expander balance regressions."""

from dataclasses import replace
import unittest

from hthp.cycles.ejector_cycle import EjectorCycle, EjectorCycleConfig
from hthp.heat_sources.fixed_temperature import FixedTemperatureHeatSource


class IntrastageEjectorExpanderTests(unittest.TestCase):
    def configs(self):
        for fluid, tev, tcd in (("R32", 20, 50), ("R1233zd(E)", 45, 125)):
            yield EjectorCycleConfig(
                refrigerant=fluid, heat_source=FixedTemperatureHeatSource(tev),
                condensation_temperature_C=tcd, heating_capacity_kW=1.0,
                subcooling_K=0.01,
            )

    def test_default_results_and_zero_efficiency_valve_limit(self):
        for config in self.configs():
            with self.subTest(fluid=config.refrigerant):
                base = EjectorCycle(config).solve()
                self.assertIsNone(base.expander)
                self.assertEqual(base.expander_shaft_power_kW, 0.0)
                self.assertEqual(base.net_shaft_power_kW, base.compressor_shaft_power_kW)
                self.assertEqual(base.net_electrical_power_kW, base.compressor_electrical_power_kW)
                zero = EjectorCycle(replace(
                    config, use_expander=True, expander_isentropic_efficiency=0,
                )).solve()
                self.assertIsNotNone(zero.expander)
                self.assertAlmostEqual(zero.heating_COP, base.heating_COP, places=11)
                self.assertAlmostEqual(zero.evaporator_heat_kW, base.evaporator_heat_kW, places=11)
                self.assertAlmostEqual(zero.states["evaporator_in"].enthalpy_kJ_kg,
                                       base.states["evaporator_in"].enthalpy_kJ_kg, places=11)

    def test_expander_uses_evaporator_mass_not_condenser_mass(self):
        for config in self.configs():
            with self.subTest(fluid=config.refrigerant):
                base = EjectorCycle(config).solve()
                result = EjectorCycle(replace(config, use_expander=True)).solve()
                self.assertGreater(result.expander_shaft_power_kW, 0)
                self.assertAlmostEqual(
                    result.expander_shaft_power_kW,
                    result.evaporator_mass_flow_kg_s * result.expander.specific_shaft_work_kJ_kg,
                    places=12,
                )
                self.assertAlmostEqual(result.entrainment_ratio, base.entrainment_ratio, places=11)
                self.assertAlmostEqual(result.separator_pressure_bar, base.separator_pressure_bar, places=11)
                self.assertGreater(result.evaporator_heat_kW, base.evaporator_heat_kW)
                self.assertGreater(result.heating_COP, base.heating_COP)
                self.assertLess(result.states["evaporator_in"].enthalpy_kJ_kg,
                                base.states["evaporator_in"].enthalpy_kJ_kg)
                self.assertLess(abs(result.energy_balance_error_kW), 1e-7)
                self.assertLess(abs(result.system_energy_balance_error_kW), 1e-7)
                self.assertLess(abs(result.separator_mass_balance_error_kg_s), 1e-8)

    def test_nonideal_recovery_separates_shaft_loss_from_useful_heat(self):
        for config in self.configs():
            for recovery in (0.0, 0.6, 1.0):
                with self.subTest(fluid=config.refrigerant, recovery=recovery):
                    result = EjectorCycle(replace(
                        config, use_expander=True,
                        expander_recovery_efficiency=recovery,
                        external_subcooling_specific_heat_kJ_kg=2.0,
                    )).solve()
                    work = result.expander_shaft_power_kW
                    self.assertAlmostEqual(result.recovered_power_kW, recovery * work)
                    self.assertAlmostEqual(result.unrecovered_expander_power_kW, (1-recovery) * work)
                    self.assertAlmostEqual(result.net_shaft_power_kW,
                                           result.compressor_shaft_power_kW - recovery * work)
                    self.assertAlmostEqual(result.net_electrical_power_kW,
                                           result.net_shaft_power_kW / config.motor_efficiency)
                    useful = result.condenser_heat_kW + result.external_subcooler_heat_kW
                    self.assertAlmostEqual(result.heating_COP,
                                           useful / result.net_electrical_power_kW)
                    self.assertLess(abs(result.energy_balance_error_kW), 1e-7)
                    self.assertLess(abs(result.system_energy_balance_error_kW), 1e-7)

    def test_invalid_expander_efficiencies_rejected_even_when_disabled(self):
        config = next(self.configs())
        for key in ("expander_isentropic_efficiency", "expander_recovery_efficiency"):
            for value in (-0.1, 1.1, float("nan"), float("inf")):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    EjectorCycle(replace(config, **{key: value})).solve()


if __name__ == "__main__":
    unittest.main()
