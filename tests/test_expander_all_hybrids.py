"""All cross-stage expander combinations retain their own physical closures."""

import csv
from dataclasses import replace
import itertools
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import matplotlib.pyplot as plt

from hthp import cli, model
from hthp.analyses import ph_analysis, record
from hthp.comparisons import comparison_views
from hthp.configurations import (ARCHITECTURES, EXPANDER_HYBRID_ARCHITECTURES,
                                  ComponentParams, LEGACY_ARCHITECTURES, technology_components)


OTHER_HYBRIDS = tuple(case for case in EXPANDER_HYBRID_ARCHITECTURES
                      if "flash_tank" not in case[1:])
CLI_TECHNOLOGY = {"expander": "expansor", "economizer": "economizador", "ejector": "ejetor"}


class AllExpanderHybridTests(unittest.TestCase):
    def params(self, low, high, **changes):
        return replace(ComponentParams(), low_technology=low, high_technology=high,
                       optimize_injection="economizer" in (low, high),
                       T_cd_l_step=0.2, **changes)

    def test_registry_is_complete_product_and_retains_historical_hybrid_order(self):
        technologies = ("simple", "flash_tank", "economizer", "ejector", "expander")
        self.assertEqual(len(ARCHITECTURES), 52)
        self.assertEqual({case[1:] for case in LEGACY_ARCHITECTURES},
                         set(itertools.product(technologies, repeat=2)))
        self.assertEqual(EXPANDER_HYBRID_ARCHITECTURES[:2], (
            ("Low-stage expander / high-stage flash tank", "expander", "flash_tank"),
            ("Low-stage flash tank / high-stage expander", "flash_tank", "expander")))
        self.assertEqual(len(OTHER_HYBRIDS), 4)
        self.assertEqual({case[1:] for case in OTHER_HYBRIDS},
                         {("expander", "economizer"), ("economizer", "expander"),
                          ("expander", "ejector"), ("ejector", "expander")})

    def test_cli_enables_all_new_placements_and_only_economizer_pressure_search(self):
        for label, low, high in OTHER_HYBRIDS:
            with self.subTest(configuration=label):
                selected, p = cli.selected_case(cli.build_parser().parse_args([
                    "--baixa", CLI_TECHNOLOGY[low], "--alta", CLI_TECHNOLOGY[high],
                    "--sem-subcooler", "--eficiencia-expansor", "0.63",
                    "--recuperacao-expansor", "0.8"]))
                self.assertEqual(selected, label)
                self.assertEqual((p.low_technology, p.high_technology), (low, high))
                self.assertEqual(p.optimize_injection, "economizer" in (low, high))
                self.assertEqual(p.expander_isentropic_efficiency, 0.63)
                self.assertEqual(p.expander_recovery_efficiency, 0.8)
                self.assertFalse(p.use_subcooler)

    def test_every_component_family_has_all_nine_configurations_and_reference(self):
        for group in ("expansor", "flash", "economizador", "ejetor"):
            view, = comparison_views(group)
            self.assertGreaterEqual(len(view.cases), 10)
            self.assertEqual(view.cases[0], ARCHITECTURES[0])
            self.assertTrue(view.all_metrics)
        mixed, = comparison_views("mistas")
        self.assertEqual(len(mixed.cases), 13)
        self.assertTrue(set(EXPANDER_HYBRID_ARCHITECTURES).issubset(mixed.cases))

    def test_physical_balances_and_component_specific_splits_with_both_subcooler_options(self):
        for label, low, high in OTHER_HYBRIDS:
            for enabled in (False, True):
                with self.subTest(configuration=label, subcooler=enabled):
                    p = self.params(low, high, use_subcooler=enabled,
                                    expander_recovery_efficiency=0.8)
                    cycle = model.ciclo_cascata(p, 45.0)
                    row = record(label, p, cycle)
                    self.assertAlmostEqual(cycle["Q_total"], 170000, places=5)
                    self.assertLess(abs(row["energy_residual_W"]), 0.02)
                    self.assertLess(abs(row["cascade_residual_W"]), 0.02)
                    self.assertAlmostEqual(row["W_net_shaft_kW"],
                        row["W_compressor_shaft_kW"] - row["W_recovered_kW"], places=8)
                    self.assertAlmostEqual(row["W_expander_shaft_kW"],
                        row["W_recovered_kW"] + row["W_recovery_loss_kW"], places=8)
                    self.assertGreater(row["W_expander_shaft_kW"], 0)
                    expander_stage = "low" if low == "expander" else "high"
                    other_stage = "high" if expander_stage == "low" else "low"
                    expansion, component = cycle[expander_stage], cycle[other_stage]
                    self.assertIsNone(expansion["P_int"])
                    self.assertEqual(expansion["injection_fraction"], 0)
                    self.assertAlmostEqual(expansion["m_dot"], expansion["m_dot_evap"], places=9)
                    self.assertTrue(cycle["low"]["N_feasible"])
                    if "economizer" in (low, high):
                        self.assertTrue(row["intermediate_pressures_optimized"])
                        self.assertEqual(set(cycle["injection_search_fractions"]),
                                         {f"injection_fraction_{other_stage}"})
                        self.assertGreater(component["P_int"], component["P_ev"])
                        self.assertLess(component["P_int"], component["P_cd"])
                        self.assertGreater(component["injection_fraction"], 0)
                        self.assertAlmostEqual(component["m_dot_evap"],
                            component["m_dot"] * (1 - component["injection_fraction"]), places=9)
                    else:
                        self.assertFalse(row["intermediate_pressures_optimized"])
                        self.assertNotIn("injection_search_fractions", cycle)
                        self.assertIsNone(component["P_int"])
                        self.assertEqual(component["injection_fraction"], 0)
                        self.assertGreater(component["P_suction"], component["P_ev"])
                        self.assertGreater(component["Q_ihx"], 0)
                        self.assertLess(abs(component["ejector_closure_residual"]), 1e-7)
                        self.assertLess(abs(component["separator_mass_residual"]), 1e-7)

    def test_zero_expander_efficiency_reproduces_the_matching_component_baseline(self):
        for label, low, high in OTHER_HYBRIDS:
            for enabled in (False, True):
                with self.subTest(configuration=label, subcooler=enabled):
                    p = self.params(low, high, use_subcooler=enabled,
                                    expander_isentropic_efficiency=0)
                    baseline = replace(p,
                        low_technology="simple" if low == "expander" else low,
                        high_technology="simple" if high == "expander" else high)
                    actual = model.ciclo_cascata(p, 45.0)
                    reference = model.ciclo_cascata(baseline, 45.0)
                    self.assertAlmostEqual(actual["COP"], reference["COP"], places=7)
                    self.assertAlmostEqual(actual["W_total"], reference["W_total"], places=3)
                    self.assertAlmostEqual(actual["low"]["Q_ev"], reference["low"]["Q_ev"], places=3)
                    self.assertAlmostEqual(record(label, p, actual)["W_expander_shaft_kW"], 0, places=8)

    def test_combined_ph_uses_each_new_architectures_own_scipy_optimum(self):
        for label, low, high in OTHER_HYBRIDS:
            with self.subTest(configuration=label):
                p = self.params(low, high)
                with patch("hthp.model.minimize_scalar", wraps=model.minimize_scalar) as search:
                    optimum, trials = model.otimizar_cascata(p)
                self.assertEqual(search.call_count, 1)
                self.assertEqual(search.call_args.kwargs["method"], "bounded")
                self.assertEqual(optimum["COP"], max(trial["COP"] for trial in trials))
                fig, ax = plt.subplots()
                with tempfile.TemporaryDirectory() as directory, \
                     patch("hthp.analyses.model.otimizar_cascata",
                           side_effect=AssertionError("Must use the supplied optimum")), \
                     patch("hthp.plots.cycles.diagrams.plot_cycles",
                           return_value=(fig, ax)) as plotted, \
                     patch("hthp.analyses.save_figure"), patch("builtins.print"):
                    ph_analysis(p, [(label, p)], Path(directory), cycles=[optimum])
                    plotted.assert_called_once()
                    circuits = plotted.call_args.args[0]
                    self.assertEqual({c["stage"] for c in circuits}, {"low", "high"})
                    expansion = next(c for c in circuits if c["stage"] ==
                                     ("low" if low == "expander" else "high"))
                    self.assertLess(expansion["H_J_kg"][4], expansion["H_J_kg"][3])
                    with (Path(directory) / "states.csv").open(newline="") as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual({row["stage"] for row in rows}, {"low", "high"})
                    self.assertTrue(all(float(row["low_condensation_C"]) == optimum["T_cd_l"]
                                        for row in rows))


if __name__ == "__main__":
    unittest.main()
