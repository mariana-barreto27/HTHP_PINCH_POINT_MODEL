"""Exact reuse of high-stage closures must not change physical calculations."""

from dataclasses import replace
import unittest
from unittest.mock import patch

from hthp import configurations as configurations
from hthp import model
from hthp.configurations import ComponentParams


class HighStageReuseTests(unittest.TestCase):
    def setUp(self):
        configurations._high_stage_closure_cached.cache_clear()

    def tearDown(self):
        configurations._high_stage_closure_cached.cache_clear()

    def test_low_stage_trials_reuse_identical_high_stage_conditions(self):
        p = ComponentParams(high_technology="ejector")
        with patch("hthp.configurations._high_stage_closure_uncached",
                   return_value={"COP": 3.0}) as solve:
            configurations.calcular_alta_com_componentes(p, 40.0, 125.0)
            configurations.calcular_alta_com_componentes(replace(
                p, low_technology="flash_tank", injection_fraction_low=0.8,
                DT_source=6.1, DT_w_cond=0.1, _evaluating_injection=True,
                analysis_family="different"), 40.0, 125.0)
        self.assertEqual(solve.call_count, 1)
        self.assertEqual(configurations._high_stage_closure_cached.cache_info().hits, 1)

    def test_physical_inputs_and_exact_temperatures_are_not_merged(self):
        p = ComponentParams(high_technology="ejector")
        changes = (
            {"Q_target": 120000.0}, {"high_technology": "flash_tank"},
            {"injection_fraction_high": 0.6}, {"use_subcooler": False},
            {"T_w_sc_in": 26.0}, {"m_dot_w_sc": 0.1},
            {"DT_pinch_sc": 15.0}, {"ejector_nozzle_efficiency": 0.6},
            {"economizer_effectiveness": 0.8}, {"expander_isentropic_efficiency": 0.6},
            {"a_is_h": 0.7}, {"F_h": "R245fa"}, {"SUP_h": 6.0},
            {"SUB_h": 1.0}, {"N_h": 50.0}, {"C_h": 0.03},
            {"eta_is_min": 0.3}, {"N_l_max": 120.0},
            {"T_sat_w_cond": 119.0},
        )
        with patch("hthp.configurations._high_stage_closure_uncached",
                   return_value={"COP": 3.0}) as solve:
            configurations.calcular_alta_com_componentes(p, 40.0, 125.0)
            for delta in changes:
                configurations.calcular_alta_com_componentes(replace(p, **delta), 40.0, 125.0)
            configurations.calcular_alta_com_componentes(p, 40.0 + 1e-12, 125.0)
            configurations.calcular_alta_com_componentes(p, 40.0, 125.0 + 1e-12)
        self.assertEqual(solve.call_count, len(changes) + 3)

    def test_cached_results_cannot_be_mutated_by_callers(self):
        p = ComponentParams(high_technology="ejector")
        with patch("hthp.configurations._high_stage_closure_uncached",
                   return_value={"COP": 3.0, "compressors": [{"m_dot": 1.0}]}):
            first = configurations.calcular_alta_com_componentes(p, 40.0, 125.0)
            first["compressors"][0]["m_dot"] = -100.0
            first["COP"] = -1.0
            second = configurations.calcular_alta_com_componentes(p, 40.0, 125.0)
        self.assertEqual(second, {"COP": 3.0, "compressors": [{"m_dot": 1.0}]})

    def test_sizing_mode_is_checked_even_when_cached(self):
        p = ComponentParams(high_technology="ejector")
        with patch("hthp.configurations._high_stage_closure_uncached",
                   return_value={"COP": 3.0}):
            configurations.calcular_alta_com_componentes(p, 40.0, 125.0)
            with patch.object(model, "MODO_DIMENSIONAMENTO", "DESLOCAMENTO"):
                with self.assertRaisesRegex(ValueError, "CAPACIDADE"):
                    configurations.calcular_alta_com_componentes(p, 40.0, 125.0)

    def test_real_stage_results_match_original_closure_exactly(self):
        for technology in ("simple", "flash_tank", "economizer", "ejector", "expander"):
            for subcooler in (False, True):
                with self.subTest(technology=technology, subcooler=subcooler):
                    p = ComponentParams(high_technology=technology, use_subcooler=subcooler)
                    original = configurations._high_stage_closure_uncached(p, 40.0, 125.0)
                    cached = configurations.calcular_alta_com_componentes(p, 40.0, 125.0)
                    self.assertEqual(cached, original)
                    self.assertAlmostEqual(cached["Q_total"], 170000.0, places=5)
                    self.assertLess(abs(cached["residual"]), 1e-5)

    def test_complete_cascade_matches_with_reuse_disabled(self):
        p = ComponentParams(low_technology="flash_tank", high_technology="ejector",
                            optimize_injection=False)
        with patch("hthp.configurations.calcular_alta_com_componentes",
                   side_effect=configurations._high_stage_closure_uncached):
            original = model.ciclo_cascata(p, 45.0)
        cached = model.ciclo_cascata(p, 45.0)
        self.assertEqual(cached, original)


if __name__ == "__main__":
    unittest.main()
