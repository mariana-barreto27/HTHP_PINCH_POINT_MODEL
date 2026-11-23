"""Cross-stage flash-tank/expander hybrids must use coupled physical calculations."""

import csv
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import matplotlib.pyplot as plt

from hthp import cli, model
from hthp.analyses import ph_analysis, record
from hthp.comparisons import comparison_views, compact_label
from hthp.configurations import (
    ARCHITECTURES, EXPANDER_HYBRID_ARCHITECTURES, ComponentParams,
)

FLASH_HYBRIDS = tuple(case for case in EXPANDER_HYBRID_ARCHITECTURES
                      if "flash_tank" in case[1:])


class ExpanderFlashHybridTests(unittest.TestCase):
    def params(self, low, high, **changes):
        return replace(ComponentParams(), low_technology=low,
                       high_technology=high, optimize_injection=True,
                       T_cd_l_step=0.2, **changes)

    def test_both_explicit_cli_placements_and_turbine_alias_are_registered(self):
        for label, low, high in FLASH_HYBRIDS:
            for expander_name in ("expansor", "turbina"):
                arguments = ["--baixa", expander_name if low == "expander" else "flash",
                             "--alta", expander_name if high == "expander" else "flash",
                             "--eficiencia-expansor", "0.63",
                             "--recuperacao-expansor", "0.8", "--sem-subcooler"]
                selected, p = cli.selected_case(cli.build_parser().parse_args(arguments))
                self.assertEqual(selected, label)
                self.assertEqual((p.low_technology, p.high_technology), (low, high))
                self.assertTrue(p.optimize_injection)
                self.assertFalse(p.use_subcooler)
                self.assertEqual(p.expander_isentropic_efficiency, 0.63)
                self.assertEqual(p.expander_recovery_efficiency, 0.8)
                self.assertIn("(low)", compact_label(label))
                self.assertIn("(high)", compact_label(label))

    def test_new_cases_appear_in_all_relevant_views(self):
        hybrids = set(FLASH_HYBRIDS)
        self.assertEqual(len(ARCHITECTURES), 52)
        for group in ("todos", "mistas", "flash", "expansor", "turbina"):
            views = comparison_views(group)
            selected = {case for view in views for case in view.cases}
            self.assertTrue(hybrids.issubset(selected), group)
        mixed, = comparison_views("mistas")
        self.assertEqual(len(mixed.cases), 13)
        self.assertTrue(mixed.all_metrics)
        flash, = comparison_views("flash")
        expansion, = comparison_views("expansor")
        self.assertGreater(len(flash.cases), 10)
        self.assertGreater(len(expansion.cases), 10)

    def test_all_dispatches_both_new_cases_without_running_physics(self):
        args = cli.build_parser().parse_args(["all"])
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(cli, "ROOT", Path(directory)), \
             patch("hthp.cli.run_selected_analysis") as selected, \
             patch("hthp.cli.run_comparison"), \
             patch("hthp.component_comparison.run_component_comparison"), patch("builtins.print"):
            try:
                cli.run_all_architectures(args)
            finally:
                args._calculation_cache.close()
        self.assertEqual(selected.call_count, len(ARCHITECTURES) * 5)
        dispatched = [call.args[0] for call in selected.call_args_list]
        for label, _, _ in FLASH_HYBRIDS:
            self.assertEqual(dispatched.count(label), 5)

    def test_mixed_plots_distinguish_net_gross_and_recovered_power(self):
        label, low, high = FLASH_HYBRIDS[0]
        p = self.params(low, high)
        args = cli.build_parser().parse_args([])
        row = dict(configuration=label, status="valid", low_condensation_C=45, COP=2.5)
        with tempfile.TemporaryDirectory() as directory, \
             patch("hthp.cli.plot_curves") as plot:
            cli._plot_architecture_curves(
                args, p, Path(directory), groups=[(label, [row])])
        by_key = {call.args[2]: call for call in plot.call_args_list}
        self.assertEqual(by_key["W_shaft_kW"].args[4], "Net shaft input [kW]")
        self.assertIn("W_compressor_shaft_kW", by_key)
        self.assertIn("W_expander_shaft_kW", by_key)
        self.assertIn("W_recovered_kW", by_key)

    def test_each_hybrid_closes_mass_energy_and_cascade_with_both_subcooler_options(self):
        for label, low, high in FLASH_HYBRIDS:
            for subcooler in (False, True):
                with self.subTest(configuration=label, subcooler=subcooler):
                    p = self.params(low, high, use_subcooler=subcooler,
                                    expander_recovery_efficiency=0.8)
                    cycle = model.ciclo_cascata(p, 45)
                    row = record(label, p, cycle)
                    self.assertAlmostEqual(cycle["Q_total"], 170000, places=5)
                    self.assertLess(abs(row["energy_residual_W"]), 0.02)
                    self.assertLess(abs(cycle["residual_cascade"]), 0.02)
                    self.assertAlmostEqual(
                        row["W_net_shaft_kW"],
                        row["W_compressor_shaft_kW"] - row["W_recovered_kW"], places=8)
                    self.assertAlmostEqual(
                        row["W_expander_shaft_kW"],
                        row["W_recovered_kW"] + row["W_recovery_loss_kW"], places=8)
                    self.assertGreater(row["W_expander_shaft_kW"], 0)
                    self.assertTrue(row["intermediate_pressures_optimized"])
                    flash_stage, expander_stage = (
                        ("high", "low") if high == "flash_tank" else ("low", "high"))
                    flash, expander = cycle[flash_stage], cycle[expander_stage]
                    self.assertEqual(set(cycle["injection_search_fractions"]),
                                     {f"injection_fraction_{flash_stage}"})
                    self.assertIsNone(expander["P_int"])
                    self.assertEqual(expander["injection_fraction"], 0)
                    self.assertGreater(flash["P_int"], flash["P_ev"])
                    self.assertLess(flash["P_int"], flash["P_cd"])
                    self.assertGreater(flash["injection_fraction"], 0)
                    self.assertAlmostEqual(
                        flash["m_dot_evap"],
                        flash["m_dot"] * (1 - flash["injection_fraction"]), places=9)
                    self.assertAlmostEqual(expander["m_dot"], expander["m_dot_evap"], places=9)

    def test_zero_expansion_efficiency_reproduces_flash_tank_with_valve_in_other_stage(self):
        for label, low, high in FLASH_HYBRIDS:
            for subcooler in (False, True):
                with self.subTest(configuration=label, subcooler=subcooler):
                    p = self.params(low, high, use_subcooler=subcooler,
                                    expander_isentropic_efficiency=0)
                    baseline = replace(p, low_technology="simple" if low == "expander" else low,
                                       high_technology="simple" if high == "expander" else high)
                    cycle = model.ciclo_cascata(p, 45)
                    reference = model.ciclo_cascata(baseline, 45)
                    self.assertAlmostEqual(cycle["COP"], reference["COP"], places=7)
                    self.assertAlmostEqual(cycle["W_total"], reference["W_total"], places=3)
                    self.assertAlmostEqual(cycle["low"]["Q_ev"], reference["low"]["Q_ev"], places=3)
                    row = record(label, p, cycle)
                    self.assertAlmostEqual(row["W_expander_shaft_kW"], 0, places=8)
                    self.assertAlmostEqual(row["W_recovered_kW"], 0, places=8)

    def test_optimized_ph_uses_both_actual_cycles_at_the_supplied_optimum(self):
        for label, low, high in FLASH_HYBRIDS:
            with self.subTest(configuration=label):
                p = self.params(low, high)
                with patch("hthp.model.minimize_scalar", wraps=model.minimize_scalar) as search:
                    optimum, trials = model.otimizar_cascata(p)
                self.assertEqual(search.call_count, 1)
                self.assertEqual(search.call_args.kwargs["method"], "bounded")
                self.assertTrue(trials)
                self.assertEqual(optimum["COP"], max(trial["COP"] for trial in trials))
                fig, ax = plt.subplots()
                with tempfile.TemporaryDirectory() as directory, \
                     patch("hthp.analyses.model.otimizar_cascata",
                           side_effect=AssertionError("Must plot supplied optimum")), \
                     patch("hthp.plots.cycles.diagrams.plot_cycles",
                           return_value=(fig, ax)) as plot, \
                     patch("hthp.analyses.save_figure"), patch("builtins.print"):
                    ph_analysis(p, [(label, p)], Path(directory), cycles=[optimum])
                    self.assertEqual(plot.call_count, 1)
                    actual_cycles = plot.call_args.args[0]
                    self.assertEqual({item["stage"] for item in actual_cycles}, {"low", "high"})
                    expander = next(item for item in actual_cycles
                                    if item["stage"] == ("low" if low == "expander" else "high"))
                    self.assertLess(expander["H_J_kg"][4], expander["H_J_kg"][3])
                    with (Path(directory) / "states.csv").open() as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual({row["stage"] for row in rows}, {"low", "high"})
                    self.assertTrue(all(float(row["low_condensation_C"]) == optimum["T_cd_l"]
                                        for row in rows))


if __name__ == "__main__":
    unittest.main()
