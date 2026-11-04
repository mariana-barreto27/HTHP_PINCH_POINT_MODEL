"""Low-level properties must preserve high-level values and avoid repeated flashes."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, get_ident
import math
import unittest
from unittest.mock import patch

from CoolProp.CoolProp import AbstractState, PropsSI

from hthp.thermo import properties
from hthp.thermo.state import ThermodynamicState


# Single-phase liquid/gas and the current and previous project refrigerants.
SINGLE_PHASE_CASES = (
    ("R32", 1e6, 315.0), ("R1233zd(E)", 5e5, 390.0),
    ("R410A", 1e6, 320.0), ("R245fa", 3e5, 365.0),
    ("Water", 1e5, 300.0), ("Air", 1e5, 295.0),
)
SATURATION_CASES = (("R32", 300.0), ("R1233zd(E)", 350.0),
                    ("R410A", 300.0), ("R245fa", 340.0), ("Water", 373.15))


class CountingState:
    """Proxy retains real CoolProp calculations while counting state updates."""

    def __init__(self, backend, fluid, updates):
        self.actual = AbstractState(backend, fluid)
        self.updates = updates

    def update(self, *args):
        self.updates.append((get_ident(), args))
        return self.actual.update(*args)

    def __getattr__(self, name):
        return getattr(self.actual, name)


class LowLevelPropertyTests(unittest.TestCase):
    def setUp(self):
        properties.clear_property_caches()

    def tearDown(self):
        properties.clear_property_caches()

    def assert_property_close(self, actual, expected):
        self.assertTrue(math.isfinite(actual))
        self.assertAlmostEqual(actual, expected, delta=max(1e-7, abs(expected) * 2e-8))

    def test_single_phase_properties_match_props_si(self):
        for fluid, pressure, temperature in SINGLE_PHASE_CASES:
            for output in ("T", "P", "H", "S", "D", "C", "O", "Q"):
                with self.subTest(fluid=fluid, output=output):
                    expected = PropsSI(output, "P", pressure, "T", temperature, fluid)
                    actual = properties.props_si_cached(
                        output, "P", pressure, "T", temperature, fluid)
                    self.assert_property_close(actual, expected)

    def test_saturated_and_two_phase_properties_match_props_si(self):
        for fluid, temperature in SATURATION_CASES:
            pressure = PropsSI("P", "T", temperature, "Q", 0, fluid)
            for quality in (0.0, 0.35, 1.0):
                for output in ("T", "H", "S", "D", "Q"):
                    with self.subTest(fluid=fluid, quality=quality, output=output):
                        expected = PropsSI(output, "P", pressure, "Q", quality, fluid)
                        actual = properties.props_si_cached(
                            output, "P", pressure, "Q", quality, fluid)
                        self.assert_property_close(actual, expected)

    def test_subcooled_refrigerant_liquid_properties_match_props_si(self):
        for fluid, saturation_temperature in SATURATION_CASES:
            pressure = PropsSI("P", "T", saturation_temperature, "Q", 0, fluid)
            temperature = saturation_temperature - 10
            for output in ("H", "S", "D", "C", "O", "Q"):
                with self.subTest(fluid=fluid, output=output):
                    expected = PropsSI(output, "P", pressure, "T", temperature, fluid)
                    actual = properties.props_si_cached(
                        output, "P", pressure, "T", temperature, fluid)
                    self.assert_property_close(actual, expected)

    def test_pressure_enthalpy_entropy_and_hs_pairs_match_props_si(self):
        for fluid, pressure, temperature in SINGLE_PHASE_CASES:
            enthalpy = PropsSI("H", "P", pressure, "T", temperature, fluid)
            entropy = PropsSI("S", "P", pressure, "T", temperature, fluid)
            for output, input1, value1, input2, value2 in (
                ("T", "P", pressure, "H", enthalpy),
                ("S", "P", pressure, "H", enthalpy),
                ("H", "P", pressure, "S", entropy),
                ("P", "H", enthalpy, "S", entropy),
            ):
                with self.subTest(fluid=fluid, pair=(input1, input2), output=output):
                    expected = PropsSI(output, input1, value1, input2, value2, fluid)
                    actual = properties.props_si_cached(
                        output, input1, value1, input2, value2, fluid)
                    self.assert_property_close(actual, expected)

    def test_reverse_input_order_preserves_results(self):
        for fluid, pressure, temperature in SINGLE_PHASE_CASES:
            forward = properties.props_si_cached("H", "P", pressure, "T", temperature, fluid)
            reverse = properties.props_si_cached("H", "T", temperature, "P", pressure, fluid)
            self.assertEqual(forward, reverse)

    def test_saturation_and_constants_convenience_functions_match(self):
        for fluid, temperature in SATURATION_CASES:
            self.assert_property_close(
                properties.saturation_pressure_Pa(fluid, temperature - 273.15),
                PropsSI("P", "T", temperature, "Q", 0, fluid))
            self.assert_property_close(properties.critical_temperature_C(fluid),
                                       PropsSI("Tcrit", fluid) - 273.15)
            for key in ("Tcrit", "pcrit", "molar_mass"):
                self.assert_property_close(properties.props_si_constant_cached(key, fluid),
                                           PropsSI(key, fluid))

    def test_alias_resolution_uses_same_physical_fluid(self):
        with patch.dict(properties.REFRIGERANT_ALIASES, {"PROJECT-R32": "R32"}):
            self.assert_property_close(
                properties.props_si_cached("H", "P", 1e6, "T", 315.0, "project-r32"),
                PropsSI("H", "P", 1e6, "T", 315.0, "R32"))

    def test_invalid_pairs_outputs_and_fluids_still_raise(self):
        for call in (
            ("H", "P", 1e6, "P", 1e6, "R32"),
            ("not_a_property", "P", 1e6, "T", 315.0, "R32"),
            ("H", "P", 1e6, "T", 315.0, "not_a_refrigerant"),
        ):
            with self.subTest(call=call), self.assertRaises(ValueError):
                properties.props_si_cached(*call)

    def test_full_state_snapshot_matches_high_level_queries(self):
        for fluid, pressure, temperature in SINGLE_PHASE_CASES:
            result = properties.state_properties_cached("P", pressure, "T", temperature, fluid)
            self.assertEqual(len(result), 4)
            for actual, key in zip(result, ("T", "H", "S", "Q")):
                expected = PropsSI(key, "P", pressure, "T", temperature, fluid)
                self.assert_property_close(actual, expected)

    def test_thermodynamic_state_constructors_preserve_units_values_and_quality(self):
        for fluid, pressure, temperature in SINGLE_PHASE_CASES:
            enthalpy = PropsSI("H", "P", pressure, "T", temperature, fluid)
            entropy = PropsSI("S", "P", pressure, "T", temperature, fluid)
            for state in (ThermodynamicState.from_pressure_temperature(
                    fluid, pressure, temperature - 273.15),
                    ThermodynamicState.from_pressure_enthalpy(fluid, pressure, enthalpy / 1000)):
                self.assert_property_close(state.pressure_Pa, pressure)
                self.assert_property_close(state.temperature_C, temperature - 273.15)
                self.assert_property_close(state.enthalpy_kJ_kg, enthalpy / 1000)
                self.assert_property_close(state.entropy_kJ_kgK, entropy / 1000)
                self.assertIsNone(state.quality)
        for fluid, temperature in SATURATION_CASES:
            pressure = PropsSI("P", "T", temperature, "Q", 0, fluid)
            for quality in (0.0, 0.35, 1.0):
                state = ThermodynamicState.from_pressure_quality(fluid, pressure, quality)
                self.assertEqual(state.quality, quality)
                self.assert_property_close(state.temperature_C,
                    PropsSI("T", "P", pressure, "Q", quality, fluid) - 273.15)
                self.assert_property_close(state.enthalpy_kJ_kg,
                    PropsSI("H", "P", pressure, "Q", quality, fluid) / 1000)

    def test_one_update_per_constructor_not_one_per_output(self):
        pressure, temperature, fluid = 1e6, 315.0, "R32"
        enthalpy = PropsSI("H", "P", pressure, "T", temperature, fluid)
        constructors = (
            lambda: ThermodynamicState.from_pressure_temperature(fluid, pressure, temperature - 273.15),
            lambda: ThermodynamicState.from_pressure_enthalpy(fluid, pressure, enthalpy / 1000),
            lambda: ThermodynamicState.from_pressure_quality(fluid, pressure, 0.35),
        )
        for constructor in constructors:
            properties.clear_property_caches()
            updates = []
            with patch.object(properties, "AbstractState",
                              side_effect=lambda backend, name: CountingState(backend, name, updates)):
                constructor()
            self.assertEqual(len(updates), 1)

    def test_scalar_outputs_reuse_update_but_never_stale_properties(self):
        updates = []
        fluid, pressure, temperature = "R32", 1e6, 315.0
        with patch.object(properties, "AbstractState",
                          side_effect=lambda backend, name: CountingState(backend, name, updates)):
            enthalpy = properties.props_si_cached("H", "P", pressure, "T", temperature, fluid)
            entropy = properties.props_si_cached("S", "P", pressure, "T", temperature, fluid)
            properties.props_si_cached("D", "T", temperature, "P", pressure, fluid)
            self.assertEqual(len(updates), 1)
            properties.props_si_cached("H", "P", pressure, "T", temperature + 10, fluid)
            self.assertEqual(len(updates), 2)
            # This cache hit must not falsely mark the active mutable state as A.
            self.assertEqual(properties.props_si_cached("H", "P", pressure, "T", temperature, fluid), enthalpy)
            density = properties.props_si_cached("D", "P", pressure, "T", temperature, fluid)
            self.assertEqual(len(updates), 3)
            self.assert_property_close(entropy, PropsSI("S", "P", pressure, "T", temperature, fluid))
            self.assert_property_close(density, PropsSI("D", "P", pressure, "T", temperature, fluid))

    def test_thread_local_state_instances_do_not_share_mutable_state(self):
        barrier = Barrier(2)
        constructed = []

        def factory(backend, fluid):
            constructed.append((get_ident(), backend, fluid))
            return AbstractState(backend, fluid)

        def calculate(temperature):
            barrier.wait(timeout=5)
            return properties.state_properties_cached("P", 1e6, "T", temperature, "R32")

        with patch.object(properties, "AbstractState", side_effect=factory):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(calculate, (315.0, 325.0)))
        self.assertEqual(len(constructed), 2)
        self.assertEqual(len({thread for thread, _, _ in constructed}), 2)
        self.assertTrue(all(backend == "HEOS" for _, backend, _ in constructed))
        for result, temperature in zip(results, (315.0, 325.0)):
            self.assert_property_close(result[1], PropsSI("H", "P", 1e6, "T", temperature, "R32"))

    def test_failed_update_invalidates_last_input_pair(self):
        updates = []

        class FailingAfterMutationState(CountingState):
            def update(self, *args):
                super().update(*args)
                if len(self.updates) == 2:
                    raise ValueError("A failed flash can leave the object partially updated")

        with patch.object(properties, "AbstractState", side_effect=lambda backend, name:
                          FailingAfterMutationState(backend, name, updates)):
            properties.props_si_cached("H", "P", 1e6, "T", 315.0, "R32")
            with self.assertRaises(ValueError):
                properties.props_si_cached("H", "P", 1e6, "T", 325.0, "R32")
            restored = properties.props_si_cached("S", "P", 1e6, "T", 315.0, "R32")
        self.assertEqual(len(updates), 3)
        self.assert_property_close(restored, PropsSI("S", "P", 1e6, "T", 315.0, "R32"))


if __name__ == "__main__":
    unittest.main()
