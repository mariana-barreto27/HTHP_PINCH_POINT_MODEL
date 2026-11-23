"""Independent balances for flash/economizer + ejector in one circuit."""

from dataclasses import replace
import math
import unittest

from hthp.cycles.injection_ejector_cycle import (
    InjectionEjectorCycle, InjectionEjectorCycleConfig,
)
from hthp.heat_sources.fixed_temperature import FixedTemperatureHeatSource


class InjectionEjectorCycleTests(unittest.TestCase):
    def config(self, **kwargs):
        return replace(InjectionEjectorCycleConfig(
            refrigerant="R1233zd(E)", heat_source=FixedTemperatureHeatSource(45),
            condensation_temperature_C=125, heating_capacity_kW=1,
            subcooling_K=0.01), **kwargs)

    def configs(self):
        for fluid, tev, tcd in (("R1233zd(E)", 45, 125), ("R32", 20, 50)):
            for mode in ("flash_tank", "economizer"):
                yield self.config(refrigerant=fluid,
                                  heat_source=FixedTemperatureHeatSource(tev),
                                  condensation_temperature_C=tcd, injection_mode=mode)

    def test_energy_mass_pressure_and_thermal_closure_both_fluids(self):
        for config in self.configs():
            with self.subTest(fluid=config.refrigerant, mode=config.injection_mode):
                r = InjectionEjectorCycle(config).solve()
                s = r.states
                self.assertLess(abs(r.energy_balance_error_kW), 1e-7)
                self.assertLess(abs(r.injection_balance_error_kW), 1e-9)
                self.assertLess(abs(r.economizer_balance_error_kW), 1e-9)
                self.assertLess(abs(r.separator_mass_balance_error_kg_s), 1e-8)
                self.assertLess(abs(r.separator_energy_balance_error_kW), 1e-7)
                self.assertLess(abs(r.ihx_balance_error_kW), 1e-10)
                self.assertLess(r.closure_residual, 1e-7)
                self.assertLess(r.evaporator_pressure_bar, r.separator_pressure_bar)
                self.assertLess(r.separator_pressure_bar, r.intermediate_pressure_bar)
                self.assertLess(r.intermediate_pressure_bar, s["condenser_out"].pressure_bar)
                self.assertGreater(r.injection_mass_fraction, 0)
                self.assertLess(r.injection_mass_fraction, 1)
                self.assertGreater(r.entrainment_ratio, 0)
                self.assertAlmostEqual(r.separator_vapor_quality,
                                       1 / (1 + r.entrainment_ratio), places=7)
                self.assertGreaterEqual(r.ihx_minimum_approach_K,
                                        config.ihx_minimum_approach_K - 1e-6)
                self.assertAlmostEqual(s["suction"].temperature_C
                                       - s["separator_vapour"].temperature_C,
                                       config.superheat_K)
                self.assertAlmostEqual(s["evaporator_out"].temperature_C
                                       - r.evaporation_temperature_C,
                                       config.superheat_K)
                for state in (s["first_discharge"], s["mixed"], s["discharge"]):
                    self.assertTrue(state.quality is None or state.quality == 1)

    def test_flow_fractions_and_compressor_weights(self):
        for config in self.configs():
            with self.subTest(fluid=config.refrigerant, mode=config.injection_mode):
                r = InjectionEjectorCycle(config).solve()
                s, total = r.states, r.total_refrigerant_mass_flow_kg_s
                main = (1 - r.injection_mass_fraction) * total
                self.assertAlmostEqual(r.main_refrigerant_mass_flow_kg_s, main)
                self.assertAlmostEqual(r.injected_vapor_mass_flow_kg_s,
                                       r.injection_mass_fraction * total)
                self.assertAlmostEqual(r.evaporator_mass_flow_kg_s,
                                       r.entrainment_ratio * main)
                self.assertAlmostEqual(r.low_compressor_shaft_power_kW,
                    main * (s["first_discharge"].enthalpy_kJ_kg - s["suction"].enthalpy_kJ_kg))
                self.assertAlmostEqual(r.high_compressor_shaft_power_kW,
                    total * (s["discharge"].enthalpy_kJ_kg - s["mixed"].enthalpy_kJ_kg))
                self.assertAlmostEqual(s["mixed"].enthalpy_kJ_kg,
                    (1 - r.injection_mass_fraction) * s["first_discharge"].enthalpy_kJ_kg
                    + r.injection_mass_fraction * s["injection_vapour"].enthalpy_kJ_kg)

    def test_flash_and_economizer_have_distinct_motive_pressures(self):
        flash = InjectionEjectorCycle(self.config(injection_mode="flash_tank")).solve()
        econ = InjectionEjectorCycle(self.config(injection_mode="economizer")).solve()
        self.assertAlmostEqual(flash.states["motive_in"].pressure_bar,
                               flash.intermediate_pressure_bar)
        self.assertAlmostEqual(econ.states["motive_in"].pressure_bar,
                               econ.states["condenser_out"].pressure_bar)
        self.assertGreater(flash.intermediate_pressure_bar, flash.separator_pressure_bar)
        self.assertNotAlmostEqual(flash.injection_mass_fraction, flash.separator_vapor_quality)
        self.assertEqual(flash.economizer_heat_kW, 0)
        self.assertIsNone(flash.economizer_minimum_approach_K)
        self.assertGreater(econ.economizer_heat_kW, 0)
        self.assertGreaterEqual(econ.economizer_minimum_approach_K, 5 - 1e-6)

    def test_heat_is_not_double_counted_and_motor_losses_are_explicit(self):
        for mode in ("flash_tank", "economizer"):
            r = InjectionEjectorCycle(self.config(
                injection_mode=mode, external_subcooling_specific_heat_kJ_kg=5)).solve()
            useful = r.condenser_heat_kW + r.external_subcooler_heat_kW
            self.assertAlmostEqual(useful, r.evaporator_heat_kW + r.total_shaft_power_kW, places=7)
            self.assertAlmostEqual(r.total_electrical_power_kW,
                r.low_compressor_electrical_power_kW + r.high_compressor_electrical_power_kW)
            self.assertAlmostEqual(r.total_electrical_power_kW,
                                   r.total_shaft_power_kW / r.config.motor_efficiency)
            self.assertAlmostEqual(r.heating_COP, useful / r.total_electrical_power_kW)
            self.assertAlmostEqual(r.motor_loss_kW,
                                   r.total_electrical_power_kW - r.total_shaft_power_kW)
            self.assertNotAlmostEqual(r.heating_COP,
                (useful + r.ihx_heat_kW + r.economizer_heat_kW) / r.total_electrical_power_kW)

    def test_ejector_and_mixer_entropy_generation_are_nonnegative(self):
        for config in self.configs():
            with self.subTest(fluid=config.refrigerant, mode=config.injection_mode):
                r = InjectionEjectorCycle(config).solve()
                s, mu, y = r.states, r.entrainment_ratio, r.injection_mass_fraction
                ejector_entropy = ((1 + mu) * s["ejector_out"].entropy_kJ_kgK
                                    - s["motive_in"].entropy_kJ_kgK
                                    - mu * s["evaporator_out"].entropy_kJ_kgK)
                mixing_entropy = (s["mixed"].entropy_kJ_kgK
                                  - (1 - y) * s["first_discharge"].entropy_kJ_kgK
                                  - y * s["injection_vapour"].entropy_kJ_kgK)
                self.assertGreaterEqual(ejector_entropy, -1e-9)
                self.assertGreaterEqual(mixing_entropy, -1e-9)

    def test_capacity_scales_and_saturated_condenser_is_supported(self):
        for mode in ("flash_tank", "economizer"):
            a = InjectionEjectorCycle(self.config(injection_mode=mode, subcooling_K=0)).solve()
            b = InjectionEjectorCycle(self.config(injection_mode=mode, subcooling_K=0,
                                                  heating_capacity_kW=170)).solve()
            self.assertEqual(a.states["condenser_out"].quality, 0)
            self.assertAlmostEqual(a.heating_COP, b.heating_COP)
            self.assertAlmostEqual(b.total_refrigerant_mass_flow_kg_s,
                                   170 * a.total_refrigerant_mass_flow_kg_s)
            self.assertLess(abs(b.energy_balance_error_kW), 1e-5)

    def test_invalid_modes_pressures_and_parameters_are_rejected(self):
        invalid = ({"injection_mode": "not_a_mode"},
                   {"intermediate_pressure_bar": 0},
                   {"intermediate_pressure_bar": 1e4},
                   {"intermediate_pressure_bar": float("nan")},
                   {"economizer_effectiveness": 0},
                   {"economizer_effectiveness": 1.1},
                   {"economizer_minimum_approach_K": -1},
                   {"ihx_minimum_approach_K": 0},
                   {"heating_capacity_kW": float("nan")},
                   {"nozzle_efficiency": 0})
        for overrides in invalid:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                InjectionEjectorCycle(self.config(**overrides)).solve()

    def test_infeasible_heat_exchangers_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "IHX"):
            InjectionEjectorCycle(self.config(ihx_minimum_approach_K=100)).solve()
        with self.assertRaisesRegex(ValueError, "economizer"):
            InjectionEjectorCycle(self.config(injection_mode="economizer",
                economizer_minimum_approach_K=100)).solve()


if __name__ == "__main__":
    unittest.main()

