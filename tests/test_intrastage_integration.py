"""Within-circuit hybrids remain distinct from the original cross-stage cases."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hthp import cli, model
from hthp.analyses import ph_analysis, record
from hthp.comparisons import comparison_views
from hthp.configurations import (ARCHITECTURES, LEGACY_ARCHITECTURES,
    INTRASTAGE_ARCHITECTURES, INTRASTAGE_TECHNOLOGIES, ComponentParams, has_injection)


class IntrastageIntegrationTests(unittest.TestCase):
    def test_registry_contains_exactly_five_requested_families_in_three_placements(self):
        self.assertEqual(ARCHITECTURES[:25], LEGACY_ARCHITECTURES)
        self.assertEqual(len(INTRASTAGE_TECHNOLOGIES), 9)
        self.assertEqual(len(INTRASTAGE_ARCHITECTURES), 27)
        self.assertEqual(len({case[0] for case in ARCHITECTURES}), 52)
        self.assertEqual(len({case[1:] for case in ARCHITECTURES}), 52)
        for technology in INTRASTAGE_TECHNOLOGIES:
            self.assertEqual({case[1:] for case in INTRASTAGE_ARCHITECTURES
                              if technology in case[1:]},
                             {(technology, "simple"), ("simple", technology),
                              (technology, technology)})
        self.assertNotIn("flash_economizer", INTRASTAGE_TECHNOLOGIES)

    def test_cli_names_reach_each_solver_and_enable_appropriate_pressure_search(self):
        for option, technology in cli.TECHNOLOGY.items():
            if technology not in INTRASTAGE_TECHNOLOGIES:
                continue
            for stage in ("baixa", "alta", "ambos"):
                with self.subTest(option=option, stage=stage):
                    _, p = cli.selected_case(cli.build_parser().parse_args([
                        "--componente", option, "--estagio", stage]))
                    self.assertEqual(p.low_technology,
                                     technology if stage != "alta" else "simple")
                    self.assertEqual(p.high_technology,
                                     technology if stage != "baixa" else "simple")
                    self.assertEqual(p.optimize_injection, has_injection(technology))

    def test_all_five_comparison_groups_include_individual_components_and_hybrids(self):
        views = comparison_views("mesmo-ciclo")
        self.assertEqual(len(views), 5)
        for group in ("flash-expansor", "economizador-expansor", "ejetor-expansor",
                      "flash-ejetor", "economizador-ejetor"):
            view, = comparison_views(group)
            self.assertTrue(view.all_metrics)
            self.assertEqual(view.cases[0], ARCHITECTURES[0])
            self.assertTrue(any(case in LEGACY_ARCHITECTURES[1:] for case in view.cases))
            self.assertTrue(any(case in INTRASTAGE_ARCHITECTURES for case in view.cases))

    def test_all_twenty_seven_hybrids_close_cascade_energy_and_correct_flow_branches(self):
        for label, low, high in INTRASTAGE_ARCHITECTURES:
            with self.subTest(configuration=label):
                p = replace(ComponentParams(), low_technology=low, high_technology=high,
                            optimize_injection=False, expander_recovery_efficiency=0.6)
                result = model.ciclo_cascata(p, 45.0)
                row = record(label, p, result)
                self.assertAlmostEqual(result["Q_total"], 170000, places=5)
                self.assertLess(abs(row["energy_residual_W"]), 0.02)
                self.assertLess(abs(row["cascade_residual_W"]), 0.02)
                self.assertAlmostEqual(row["W_net_shaft_kW"],
                    row["W_compressor_shaft_kW"]-row["W_recovered_kW"], places=8)
                for name, technology in (("low", low), ("high", high)):
                    if technology not in INTRASTAGE_TECHNOLOGIES:
                        continue
                    stage = result[name]
                    self.assertLess(abs(stage["residual"]), 0.02)
                    if has_injection(technology):
                        y, mass = stage["injection_fraction"], stage["m_dot"]
                        self.assertGreater(y, 0)
                        self.assertLess(y, 1)
                        self.assertAlmostEqual(stage["compressors"][0]["m_dot"], (1-y)*mass)
                        self.assertAlmostEqual(stage["compressors"][1]["m_dot"], mass)
                        if technology in ("flash_ejector", "economizer_ejector"):
                            self.assertLess(stage["P_ev"], stage["P_separator"])
                            self.assertLess(stage["P_separator"], stage["P_int"])
                            self.assertAlmostEqual(stage["m_dot_evap"],
                                stage["ejector_entrainment_ratio"]*(1-y)*mass)
                        else:
                            self.assertAlmostEqual(stage["m_dot_evap"], (1-y)*mass)

    def test_hybrid_injection_pressure_uses_scipy_and_closes_whole_cascade(self):
        for technology in ("flash_expander_both", "economizer_expander_main",
                           "flash_ejector", "economizer_ejector"):
            with self.subTest(technology=technology):
                p = replace(ComponentParams(), high_technology=technology,
                            optimize_injection=True, injection_coordinate_passes=1,
                            injection_grid_points=5, use_subcooler=False)
                result = model.ciclo_cascata(p, 45)
                self.assertIn("injection_fraction_high", result["injection_search_fractions"])
                self.assertGreater(result["injection_search_evaluations"], 5)
                self.assertTrue(record(technology, p, result)["intermediate_pressures_optimized"])
                self.assertAlmostEqual(result["Q_total"], 170000, places=5)

    def test_ph_connections_cover_both_circuits_and_hybrid_own_states(self):
        for technology in INTRASTAGE_TECHNOLOGIES:
            with self.subTest(technology=technology), tempfile.TemporaryDirectory() as directory:
                p = replace(ComponentParams(), high_technology=technology,
                            optimize_injection=False)
                result = model.ciclo_cascata(p, 45)
                with patch("hthp.analyses.save_figure") as save:
                    ph_analysis(p, [(technology, p)], Path(directory), cycles=[result])
                self.assertEqual(save.call_count, 1)
                fig = save.call_args.args[0]
                self.assertEqual(len(fig.axes[0].get_legend().get_texts()), 2)
                self.assertTrue((Path(directory) / "states.csv").exists())


if __name__ == "__main__":
    unittest.main()
