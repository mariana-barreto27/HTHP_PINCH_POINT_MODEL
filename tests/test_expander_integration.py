"""Like-for-like cascade expansion-work recovery and command-line regression."""

import csv
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import matplotlib.pyplot as plt
import numpy as np

from hthp import model
from hthp.analyses import ph_analysis, record
from hthp.cli import (build_parser, main, run_all_architectures,
                      run_comparison, selected_case)
from hthp.comparisons import comparison_views
from hthp.configurations import (ARCHITECTURES, EXPANDER_ARCHITECTURES,
                                 EXPANDER_HYBRID_ARCHITECTURES,
                                 ComponentParams)


class ExpanderIntegrationTests(unittest.TestCase):
    def params(self, low="expander", high="expander", **changes):
        return replace(ComponentParams(), low_technology=low, high_technology=high,
                       optimize_injection=False, **changes)

    def test_zero_expansion_efficiency_reproduces_the_valve_with_and_without_subcooler(self):
        for enabled in (False, True):
            reference = model.ciclo_cascata(
                replace(ComponentParams(), use_subcooler=enabled), 45)
            for label, low, high in EXPANDER_ARCHITECTURES:
                with self.subTest(configuration=label, subcooler=enabled):
                    p = self.params(low, high, use_subcooler=enabled,
                                    expander_isentropic_efficiency=0)
                    cycle = model.ciclo_cascata(p, 45)
                    self.assertAlmostEqual(cycle["COP"], reference["COP"], places=7)
                    self.assertAlmostEqual(cycle["W_total"], reference["W_total"], places=3)
                    self.assertAlmostEqual(cycle["low"]["Q_ev"], reference["low"]["Q_ev"], places=3)
                    self.assertAlmostEqual(cycle["Q_total"], 170000, places=5)
                    for name in ("low", "high"):
                        stage = cycle[name]
                        self.assertAlmostEqual(stage.get("W_expander", 0), 0, places=8)
                        self.assertAlmostEqual(stage["m_dot"], reference[name]["m_dot"], places=8)

    def test_each_placement_closes_heat_power_and_cascade_for_nonideal_recovery(self):
        for enabled in (False, True):
            for recovery in (1.0, 0.8):
                for label, low, high in EXPANDER_ARCHITECTURES:
                    with self.subTest(configuration=label, subcooler=enabled, recovery=recovery):
                        p = self.params(low, high, use_subcooler=enabled,
                                        expander_recovery_efficiency=recovery)
                        cycle = model.ciclo_cascata(p, 45)
                        row = record(label, p, cycle)
                        self.assertAlmostEqual(cycle["Q_total"], 170000, places=5)
                        self.assertLess(abs(row["energy_residual_W"]), 0.02)
                        self.assertLess(abs(cycle["residual_cascade"]), 0.02)
                        self.assertFalse(row["intermediate_pressures_optimized"])
                        self.assertAlmostEqual(row["W_shaft_kW"], row["W_net_shaft_kW"])
                        self.assertAlmostEqual(
                            row["W_net_shaft_kW"],
                            row["W_compressor_shaft_kW"] - row["W_recovered_kW"], places=8)
                        self.assertAlmostEqual(
                            row["W_expander_shaft_kW"],
                            row["W_recovered_kW"] + row["W_recovery_loss_kW"], places=8)
                        self.assertAlmostEqual(
                            cycle["Q_total"] + row["W_recovery_loss_kW"] * 1000,
                            cycle["low"]["Q_ev"] + cycle["W_total"], places=3)
                        for name, technology in (("low", low), ("high", high)):
                            if technology != "expander":
                                continue
                            stage = cycle[name]
                            states = stage["component_states"]
                            inlet, outlet = states["3E"], states[4]
                            self.assertLess(outlet.enthalpy_kJ_kg, inlet.enthalpy_kJ_kg)
                            self.assertGreaterEqual(outlet.entropy_kJ_kgK + 1e-9,
                                                    inlet.entropy_kJ_kgK)
                            self.assertAlmostEqual(outlet.pressure_bar, stage["P_ev"], places=8)
                            self.assertIsNone(stage["P_int"])
                            self.assertEqual(stage["injection_fraction"], 0)
                            self.assertAlmostEqual(stage["m_dot"], stage["m_dot_evap"], places=9)
                            self.assertGreater(stage["W_expander"], 0)
                            self.assertAlmostEqual(stage["W_recovered"],
                                                   recovery * stage["W_expander"], places=6)
                            self.assertAlmostEqual(stage["W"],
                                                   stage["W_compressor"] - stage["W_recovered"], places=6)
                            self.assertAlmostEqual(
                                stage["Q_total"] - stage["Q_ev"] - stage["W_compressor"]
                                + stage["W_expander"], 0, places=5)
                            self.assertLess(abs(stage["residual"]), 0.02)
                            self.assertAlmostEqual(row[name + "_compressor_shaft_power_kW"],
                                                   stage["W_compressor"] / 1000, places=8)
                            self.assertAlmostEqual(row[name + "_expander_shaft_power_kW"],
                                                   stage["W_expander"] / 1000, places=8)
                            self.assertAlmostEqual(row[name + "_recovered_power_kW"],
                                                   stage["W_recovered"] / 1000, places=8)
                            self.assertAlmostEqual(row[name + "_unrecovered_power_kW"],
                                                   stage["W_recovery_loss"] / 1000, places=8)

    def test_expansion_changes_the_source_heat_and_is_not_only_a_cop_subtraction(self):
        reference = model.ciclo_cascata(ComponentParams(), 45)
        cycle = model.ciclo_cascata(self.params(), 45)
        self.assertNotAlmostEqual(cycle["low"]["Q_ev"], reference["low"]["Q_ev"], places=2)
        self.assertGreater(cycle["high"]["Q_ev"], reference["high"]["Q_ev"])
        self.assertGreater(cycle["low"]["m_dot"], reference["low"]["m_dot"])
        self.assertGreater(cycle["COP"], reference["COP"])

    def test_no_recovered_work_does_not_turn_the_expander_back_into_a_valve(self):
        cycle = model.ciclo_cascata(self.params(expander_recovery_efficiency=0), 45)
        row = record("No useful recovery", self.params(expander_recovery_efficiency=0), cycle)
        self.assertEqual(row["W_recovered_kW"], 0)
        self.assertGreater(row["W_expander_shaft_kW"], 0)
        self.assertAlmostEqual(row["W_shaft_kW"], row["W_compressor_shaft_kW"])
        self.assertGreater(row["W_recovery_loss_kW"], 0)
        self.assertLess(abs(row["energy_residual_W"]), 0.02)

    def test_optimum_uses_scipy_temperature_search_and_keeps_the_fixed_duty(self):
        p = self.params(T_cd_l_step=0.2)
        with patch("hthp.model.minimize_scalar", wraps=model.minimize_scalar) as optimizer:
            optimum, evaluated = model.otimizar_cascata(p)
        self.assertEqual(optimizer.call_count, 1)
        self.assertEqual(optimizer.call_args.kwargs["method"], "bounded")
        self.assertTrue(evaluated)
        self.assertAlmostEqual(optimum["COP"], max(item["COP"] for item in evaluated))
        self.assertAlmostEqual(optimum["Q_total"], 170000, places=5)
        self.assertLess(abs(record("Optimum", p, optimum)["energy_residual_W"]), 0.02)

    def test_combined_ph_connects_both_expander_cycles_at_the_supplied_optimum(self):
        p = self.params()
        cycle = model.ciclo_cascata(p, 45)
        fig, ax = plt.subplots()
        with tempfile.TemporaryDirectory() as directory, \
             patch("hthp.analyses.model.otimizar_cascata", return_value=(cycle, [])) as optimum, \
             patch("hthp.plots.cycles.diagrams.plot_cycles", return_value=(fig, ax)) as plot, \
             patch("hthp.analyses.save_figure"), patch("builtins.print"):
            ph_analysis(p, [("Expanders in both stages", p)], Path(directory))
            optimum.assert_called_once_with(p)
            self.assertEqual(plot.call_count, 1)
            plotted_cycles = plot.call_args.args[0]
            self.assertEqual({item["stage"] for item in plotted_cycles}, {"low", "high"})
            for item in plotted_cycles:
                self.assertEqual(len(item["connections"]), 5)
                # State 3E -> 4 is the real expansion, not an isenthalpic vertical line.
                self.assertLess(item["H_J_kg"][4], item["H_J_kg"][3])
            with (Path(directory) / "states.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual({row["stage"] for row in rows}, {"low", "high"})
            self.assertTrue(all(float(row["low_condensation_C"]) == 45 for row in rows))


class ExpanderCommandTests(unittest.TestCase):
    def args(self, *extra):
        return build_parser().parse_args([
            "--eficiencia-expansor", "0.63", "--recuperacao-expansor", "0.8", *extra])

    def fake_curves(self, args, p, cases):
        temperatures = np.linspace(p.T_cd_l_min, model.T_cd_l_max(p), args.pontos)
        return [(label, [dict(configuration=label, status="valid", COP=2.2,
                              with_high_stage_subcooler=p.use_subcooler,
                              low_condensation_C=float(t), W_shaft_kW=80,
                              W_net_shaft_kW=80, W_compressor_shaft_kW=90,
                              W_expander_shaft_kW=12.5, W_recovered_kW=10,
                              W_recovery_loss_kW=2.5, low_discharge_C=90,
                              high_discharge_C=140, low_minimum_efficiency=0.75,
                              high_minimum_efficiency=0.72) for t in temperatures])
                for label, _, _ in cases]

    def fake_optima(self, args, p, cases):
        return [dict(rows[0], low_condensation_C=45)
                for _, rows in self.fake_curves(args, p, cases)]

    def assert_params(self, p):
        self.assertEqual(p.expander_isentropic_efficiency, 0.63)
        self.assertEqual(p.expander_recovery_efficiency, 0.8)

    def test_cli_alias_and_each_placement_keep_efficiencies_explicit(self):
        placements = {"alta": ("simple", "expander"),
                      "baixa": ("expander", "simple"), "ambos": ("expander", "expander")}
        for component in ("expansor", "turbina"):
            for location, expected in placements.items():
                with self.subTest(component=component, location=location):
                    _, p = selected_case(self.args("--componente", component, "--estagio", location))
                    self.assertEqual((p.low_technology, p.high_technology), expected)
                    self.assert_params(p)
                    self.assertFalse(p.optimize_injection)
        _, p = selected_case(self.args("--alta", "expansor"))
        self.assertEqual((p.low_technology, p.high_technology), ("simple", "expander"))

    def test_invalid_nonfinite_or_out_of_range_efficiencies_fail_before_running(self):
        for flag in ("--eficiencia-expansor", "--recuperacao-expansor"):
            for value in ("-0.1", "1.01", "nan", "inf", "-inf"):
                with self.subTest(flag=flag, value=value), patch("sys.stderr"), \
                     patch("hthp.cli.run_selected_analysis") as run:
                    with self.assertRaises(SystemExit):
                        main(["--componente", "expansor", flag, value])
                    run.assert_not_called()

    def test_expander_view_has_the_conventional_reference_and_all_power_metrics(self):
        from hthp.configurations import technology_components
        view, = comparison_views("expansor")
        self.assertEqual(view.cases, (ARCHITECTURES[0],) + tuple(
            case for case in ARCHITECTURES[1:]
            if any("expander" in technology_components(t) for t in case[1:])))
        self.assertTrue(view.all_metrics)
        self.assertEqual(view.reference, "Conventional cascade")

    def test_comparison_threads_efficiencies_into_physics_and_saved_conditions(self):
        args = self.args("--analise", "comparacao", "--grupo", "expansor", "--pontos", "3")
        with tempfile.TemporaryDirectory() as directory, \
             patch("hthp.cli._calculate_comparison_optima", side_effect=self.fake_optima) as optima, \
             patch("hthp.cli._calculate_architecture_curves", side_effect=self.fake_curves) as curves, \
             patch("hthp.cli.plot_curves"), patch("builtins.print"):
            run_comparison(args, Path(directory))
            self.assert_params(optima.call_args.args[1])
            self.assert_params(curves.call_args.args[1])
            view, = comparison_views("expansor")
            metadata = json.loads((Path(directory) / view.folder / "conditions.json").read_text())
            self.assertEqual(metadata["parameters"]["expander_isentropic_efficiency"], 0.63)
            self.assertEqual(metadata["parameters"]["expander_recovery_efficiency"], 0.8)

    def test_subcooler_comparison_threads_efficiencies_into_both_variants(self):
        args = self.args("--analise", "comparacao", "--grupo", "expansor",
                         "--comparar-subcooler", "--pontos", "3")
        with tempfile.TemporaryDirectory() as directory, \
             patch("hthp.cli._calculate_comparison_optima", side_effect=self.fake_optima) as optima, \
             patch("hthp.cli._calculate_architecture_curves", side_effect=self.fake_curves) as curves, \
             patch("hthp.component_comparison.plot_curves"), patch("builtins.print"):
            run_comparison(args, Path(directory))
            self.assertEqual(optima.call_count, 2)
            self.assertEqual(curves.call_count, 2)
            self.assertEqual({call.args[1].use_subcooler for call in curves.call_args_list}, {False, True})
            for call in optima.call_args_list + curves.call_args_list:
                self.assert_params(call.args[1])

    def test_expander_replot_requires_complete_power_metrics_without_recalculating(self):
        args = self.args("--analise", "comparacao", "--grupo", "expansor", "--pontos", "3")
        with tempfile.TemporaryDirectory() as directory, patch("hthp.cli.plot_curves"), patch("builtins.print"):
            output = Path(directory)
            with patch("hthp.cli._calculate_comparison_optima", side_effect=self.fake_optima), \
                 patch("hthp.cli._calculate_architecture_curves", side_effect=self.fake_curves):
                run_comparison(args, output)
            args.replotar = True
            with patch("hthp.cli._calculate_comparison_optima", side_effect=AssertionError("must reuse")), \
                 patch("hthp.cli._calculate_architecture_curves", side_effect=AssertionError("must reuse")):
                run_comparison(args, output)
                view, = comparison_views("expansor")
                data = output / view.folder / "architecture_temperature_sweeps.csv"
                data.write_text(data.read_text().replace("W_recovered_kW", "missing_recovery"))
                with self.assertRaisesRegex(ValueError, "W_recovered_kW"):
                    run_comparison(args, output)

    def test_run_all_includes_expanders_and_threads_efficiency_without_solving(self):
        args = self.args("all")
        with patch("hthp.cli.run_selected_analysis") as selected, \
             patch("hthp.cli.run_comparison"), \
             patch("hthp.component_comparison.run_component_comparison"), patch("builtins.print"):
            run_all_architectures(args)
        self.assertEqual(selected.call_count, 5 * len(ARCHITECTURES))
        for call in selected.call_args_list:
            self.assert_params(call.args[1])
        self.assertTrue({label for label, _, _ in EXPANDER_ARCHITECTURES}.issubset(
            {call.args[0] for call in selected.call_args_list}))


if __name__ == "__main__":
    unittest.main()
