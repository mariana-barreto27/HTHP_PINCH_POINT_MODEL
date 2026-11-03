"""Regression of the original base case and the three new placements."""

from dataclasses import replace
import unittest

from hthp import model
from hthp.analyses import record
from hthp.cli import build_parser, selected_case
from hthp.cli import run_all_architectures
from hthp.configurations import ARCHITECTURES, ComponentParams
from unittest.mock import patch


class EjectorIntegrationTests(unittest.TestCase):
    def test_original_conventional_case_is_unchanged(self):
        c = model.ciclo_cascata(ComponentParams(), 45)
        # Compare to the original unextended reference functions using the
        # SAME property library, rather than locking a particular CoolProp EOS.
        reference = model.ciclo_cascata(model.Params(), 45)
        self.assertAlmostEqual(c["COP"], reference["COP"], places=12)
        self.assertAlmostEqual(c["W_total"], reference["W_total"], places=7)
        self.assertEqual(c["Q_total"], 170000)

    def test_all_ejector_placements_close_at_the_reference_point(self):
        for low, high in (("simple", "ejector"), ("ejector", "simple"),
                          ("ejector", "ejector")):
            with self.subTest(low=low, high=high):
                p = replace(ComponentParams(), low_technology=low, high_technology=high)
                c = model.ciclo_cascata(p, 45)
                self.assertAlmostEqual(c["Q_total"], 170000, places=5)
                self.assertLess(abs(c["Q_total"]-c["W_total"]-c["low"]["Q_ev"]), 0.01)
                self.assertLess(abs(c["residual_cascade"]), 0.01)
                row = record("test", p, c)
                self.assertFalse(row["intermediate_pressures_optimized"])
                for stage, technology in (("low", low), ("high", high)):
                    if technology != "ejector":
                        continue
                    s = c[stage]
                    self.assertGreater(s["P_suction"], s["P_ev"])
                    self.assertAlmostEqual(s["compressor_superheat_K"], 5)
                    self.assertAlmostEqual(s["evaporator_superheat_K"], 5)
                    self.assertAlmostEqual(s["m_dot_evap"],
                                           s["m_dot"]*s["ejector_entrainment_ratio"])
                    self.assertAlmostEqual(s["Q_ev"], s["m_dot_evap"]*(s["H_evap_out"]-s["H5"]), places=6)
                    self.assertEqual(s["injection_fraction"], 0)
                    self.assertIsNone(s["P_int"])
                    self.assertGreater(s["Q_ihx"], 0)
                    self.assertAlmostEqual(row[stage+"_suction_pressure_bar"], s["P_suction"])

    def test_without_water_subcooler_keeps_the_ihx(self):
        p = replace(ComponentParams(), high_technology="ejector", use_subcooler=False)
        c = model.ciclo_cascata(p, 45)
        self.assertEqual(c["high"]["Q_sc"], 0)
        self.assertGreater(c["high"]["Q_ihx"], 0)
        self.assertAlmostEqual(c["Q_total"], 170000)

    def test_command_line_and_architecture_registry(self):
        self.assertEqual(len(ARCHITECTURES), 19)
        parser = build_parser()
        for stage in ("alta", "baixa", "ambos"):
            args = parser.parse_args(["--componente", "ejetor", "--estagio", stage])
            label, p = selected_case(args)
            self.assertIn("IHX", label)
            self.assertTrue("ejector" in (p.low_technology, p.high_technology))
        _, p = selected_case(parser.parse_args([]))
        self.assertEqual((p.low_technology, p.high_technology), ("simple", "simple"))

    def test_run_all_dispatches_every_analysis_for_all_cases(self):
        args = build_parser().parse_args(["all"])
        with patch("hthp.cli.run_selected_analysis") as selected, \
             patch("hthp.cli.run_comparison") as comparison, \
             patch("hthp.component_comparison.run_component_comparison") as additions, \
             patch("builtins.print"):
            run_all_architectures(args)
        self.assertEqual(selected.call_count, 5*len(ARCHITECTURES))
        comparison.assert_called_once()
        additions.assert_called_once()
        labels = {call.args[0] for call in selected.call_args_list}
        self.assertEqual(labels, {case[0] for case in ARCHITECTURES})


if __name__ == "__main__":
    unittest.main()
