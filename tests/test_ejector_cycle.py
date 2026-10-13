"""Balance and physical-limit tests independent of the cascade adapter."""

from dataclasses import replace
import unittest

from hthp.components.ejector import TwoPhaseEjector
from hthp.cycles.ejector_cycle import EjectorCycle, EjectorCycleConfig
from hthp.heat_sources.fixed_temperature import FixedTemperatureHeatSource


class EjectorCycleTests(unittest.TestCase):
    def config(self, **kwargs):
        return replace(EjectorCycleConfig(
            refrigerant="R1233zd(E)", heat_source=FixedTemperatureHeatSource(45),
            condensation_temperature_C=125, heating_capacity_kW=1,
            subcooling_K=0.01), **kwargs)

    def test_energy_mass_ihx_and_pressure_closures(self):
        r = EjectorCycle(self.config()).solve()
        self.assertLess(abs(r.energy_balance_error_kW), 1e-7)
        self.assertLess(abs(r.separator_mass_balance_error_kg_s), 1e-8)
        self.assertLess(abs(r.ihx_balance_error_kW), 1e-10)
        self.assertLess(r.closure_residual, 1e-7)
        self.assertGreater(r.separator_pressure_bar, r.evaporator_pressure_bar)
        self.assertLess(r.separator_pressure_bar, r.states["condenser_out"].pressure_bar)
        self.assertAlmostEqual(r.separator_vapor_quality, 1/(1+r.entrainment_ratio), places=7)
        self.assertAlmostEqual(r.evaporator_mass_flow_kg_s,
                               r.entrainment_ratio*r.refrigerant_mass_flow_kg_s)
        self.assertGreater(r.ihx_heat_kW, 0)
        self.assertGreaterEqual(r.ihx_minimum_approach_K, 5-1e-6)
        s = r.states
        self.assertAlmostEqual(s["suction"].temperature_C-s["separator_vapour"].temperature_C, 5)
        self.assertAlmostEqual(s["evaporator_out"].temperature_C-r.evaporation_temperature_C, 5)
        self.assertGreater(r.compressor_shaft_power_kW, 0)
        self.assertGreater(r.compressor_electrical_power_kW, r.compressor_shaft_power_kW)
        self.assertAlmostEqual(r.heating_COP, 1/r.compressor_electrical_power_kW)
        # Internal heat is not counted as useful output.
        self.assertNotAlmostEqual(r.heating_COP,
                                  (1+r.ihx_heat_kW)/r.compressor_electrical_power_kW)
        mu = r.entrainment_ratio
        entropy_generation = ((1+mu)*s["ejector_out"].entropy_kJ_kgK
                              - s["motive_in"].entropy_kJ_kgK
                              - mu*s["evaporator_out"].entropy_kJ_kgK)
        self.assertGreaterEqual(entropy_generation, -1e-9)

    def test_capacity_scales_without_a_cop_multiplier(self):
        a = EjectorCycle(self.config(heating_capacity_kW=1)).solve()
        b = EjectorCycle(self.config(heating_capacity_kW=4)).solve()
        self.assertAlmostEqual(a.heating_COP, b.heating_COP)
        self.assertAlmostEqual(b.refrigerant_mass_flow_kg_s, 4*a.refrigerant_mass_flow_kg_s)

    def test_liquid_and_saturated_condenser_outlets(self):
        r = EjectorCycle(self.config(subcooling_K=0)).solve()
        self.assertLess(abs(r.energy_balance_error_kW), 1e-7)
        self.assertEqual(r.states["condenser_out"].quality, 0)

    def test_low_stage_refrigerant(self):
        r = EjectorCycle(self.config(refrigerant="R32",
                                     heat_source=FixedTemperatureHeatSource(20),
                                     condensation_temperature_C=50)).solve()
        self.assertLess(abs(r.energy_balance_error_kW), 1e-7)
        self.assertGreater(r.ejector.pressure_lift_ratio, 1)

    def test_impossible_ihx_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "IHX"):
            EjectorCycle(self.config(ihx_minimum_approach_K=100)).solve()

    def test_invalid_component_efficiencies_are_rejected(self):
        for efficiency in (0, -0.1, 1.1, float("nan")):
            with self.subTest(efficiency=efficiency), self.assertRaises(ValueError):
                TwoPhaseEjector(nozzle_efficiency=efficiency)


if __name__ == "__main__":
    unittest.main()
