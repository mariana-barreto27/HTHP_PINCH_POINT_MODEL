"""Paired component comparisons must actually toggle the high-stage subcooler."""

import csv
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from hthp import model
from hthp.analyses import plot_curves, record
from hthp.cli import build_parser, main, run_comparison
from hthp.component_comparison import pair_results, variant_label
from hthp.configurations import ARCHITECTURES, ComponentParams
from hthp.comparisons import comparison_views


class ComponentAdditionTests(unittest.TestCase):
    def fake_optima(self, args, p, cases):
        return [dict(configuration=label, status="valid", COP=2+0.1*p.use_subcooler,
                     low_condensation_C=45, with_high_stage_subcooler=p.use_subcooler)
                for label, _, _ in cases]

    def fake_curves(self, args, p, cases):
        return [(label, [dict(configuration=label, status="valid", COP=2+0.1*p.use_subcooler,
                              low_condensation_C=float(t), with_high_stage_subcooler=p.use_subcooler,
                              W_shaft_kW=80, W_net_shaft_kW=80,
                              W_compressor_shaft_kW=90, W_expander_shaft_kW=12.5,
                              W_recovered_kW=10, W_recovery_loss_kW=2.5,
                              low_discharge_C=90, high_discharge_C=140,
                              low_minimum_efficiency=0.75, high_minimum_efficiency=0.72)
                         for t in np.linspace(p.T_cd_l_min, model.T_cd_l_max(p), args.pontos)])
                for label, _, _ in cases]

    def test_pairing_preserves_original_data_and_unique_case_ids(self):
        args = build_parser().parse_args([])
        data = {enabled: (self.fake_optima(args, replace(ComponentParams(), use_subcooler=enabled), ARCHITECTURES),
                          self.fake_curves(args, replace(ComponentParams(), use_subcooler=enabled), ARCHITECTURES))
                for enabled in (False, True)}
        summaries, groups = pair_results(data)
        self.assertEqual(len(summaries), 2 * len(ARCHITECTURES))
        self.assertEqual(len({name for name, _ in groups}), 2 * len(ARCHITECTURES))
        self.assertNotIn("base_configuration", data[False][1][0][1][0])
        self.assertIn((variant_label("Conventional cascade", False)), dict(groups))
        self.assertFalse(groups[0][1][0]["with_high_stage_subcooler"])

    def test_outputs_both_versions_same_bare_reference_and_replot_without_solving(self):
        args = build_parser().parse_args(["--analise", "comparacao", "--comparar-subcooler",
                                         "--grupo", "economizador", "--pontos", "3"])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch("hthp.cli._calculate_comparison_optima", side_effect=self.fake_optima) as optimum, \
                 patch("hthp.cli._calculate_architecture_curves", side_effect=self.fake_curves) as curves, \
                 patch("hthp.component_comparison.plot_curves") as plot, patch("builtins.print"):
                run_comparison(args, output)
            self.assertEqual(optimum.call_count, 2)
            self.assertEqual(curves.call_count, 2)
            self.assertEqual({call.args[1].use_subcooler for call in curves.call_args_list}, {True, False})
            for name, value in asdict(curves.call_args_list[0].args[1]).items():
                if name != "use_subcooler":
                    self.assertEqual(value, asdict(curves.call_args_list[1].args[1])[name])
            destination = output / "adicao_componentes/por_componente/economizador"
            metadata = json.loads((destination / "conditions.json").read_text())
            self.assertEqual(metadata["reference"], variant_label("Conventional cascade", False))
            cases_by_name = {variant_label(label, enabled): (low, high, enabled)
                             for label, low, high in ARCHITECTURES for enabled in (False, True)}
            for item in metadata["case_parameters"]:
                expected_low, expected_high, expected_subcooler = cases_by_name[item["configuration"]]
                self.assertEqual(item["parameters"]["low_technology"], expected_low)
                self.assertEqual(item["parameters"]["high_technology"], expected_high)
                self.assertEqual(item["parameters"]["use_subcooler"], expected_subcooler)
            with (destination / "optima.csv").open() as stream:
                self.assertEqual(len(list(csv.DictReader(stream))),
                                 2 * len(comparison_views("economizador")[0].cases))
            self.assertTrue(all(call.kwargs['subcooler_comparison'] for call in plot.call_args_list))
            self.assertNotIn("legend_title", plot.call_args_list[0].kwargs)
            with (destination / "cop_gains.csv").open() as stream:
                for row in csv.DictReader(stream):
                    expected = 5 if row["with_high_stage_subcooler"] == "True" else 0
                    self.assertAlmostEqual(float(row["COP_gain_percent"]), expected)
            args.replotar = True
            with patch("hthp.cli._calculate_comparison_optima", side_effect=AssertionError("must reuse")), \
                 patch("hthp.cli._calculate_architecture_curves", side_effect=AssertionError("must reuse")), \
                 patch("hthp.component_comparison.plot_curves"), patch("builtins.print"):
                run_comparison(args, output)
                args.carga = 120
                with self.assertRaisesRegex(ValueError, "Faltam resultados"):
                    run_comparison(args, output)
            self.assertFalse((output / "optima.csv").exists())

    def test_all_flag_and_invalid_analysis_options(self):
        with patch("hthp.component_comparison.run_component_comparison") as run, \
             tempfile.TemporaryDirectory() as directory:
            args = build_parser().parse_args(["--analise", "comparacao", "--comparar-subcooler"])
            run_comparison(args, Path(directory))
            run.assert_called_once()
        with patch("sys.stderr"):
            for argv in (["--analise", "ph", "--comparar-subcooler"],
                         ["--analise", "comparacao", "--comparar-subcooler", "--sem-subcooler"]):
                with self.assertRaises(SystemExit):
                    main(argv)

    def test_paired_plot_uses_same_color_and_different_line_styles(self):
        args = build_parser().parse_args(["--pontos", "3"])
        data = {enabled: ([], self.fake_curves(args, replace(ComponentParams(), use_subcooler=enabled),
                                              ARCHITECTURES[:1])) for enabled in (False, True)}
        _, groups = pair_results(data)
        with patch("hthp.analyses.save_figure") as save:
            plot_curves(groups, "low_condensation_C", "COP", "Temperature", "COP", "Comparison",
                        Path("unused"), ComponentParams(), subcooler_comparison=True)
        figure = save.call_args.args[0]
        first, second = figure.axes[0].lines
        self.assertEqual(first.get_color(), second.get_color())
        self.assertEqual(first.get_linestyle(), "--")
        self.assertEqual(second.get_linestyle(), "-")
        self.assertIn("with / without high-stage subcooler", figure.axes[0].get_title())

    def test_large_legend_does_not_cover_x_axis_label(self):
        args = build_parser().parse_args(["--pontos", "3"])
        data = {enabled: ([], self.fake_curves(args, replace(ComponentParams(), use_subcooler=enabled),
                                              ARCHITECTURES)) for enabled in (False, True)}
        _, groups = pair_results(data)
        with patch("hthp.analyses.save_figure") as save:
            plot_curves(groups, "low_condensation_C", "COP", "Low-stage condensation temperature [°C]",
                        "Overall COP [-]", "All combinations", Path("unused"), ComponentParams(),
                        subcooler_comparison=True)
        figure = save.call_args.args[0]
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        canvas = FigureCanvasAgg(figure)
        canvas.draw()
        renderer = canvas.get_renderer()
        ax = figure.axes[0]
        self.assertFalse(ax.xaxis.label.get_window_extent(renderer).overlaps(
            ax.get_legend().get_window_extent(renderer)))

    def test_turning_water_subcooler_off_retains_duty_and_has_zero_subcooler_heat(self):
        for label, low, high in ARCHITECTURES:
            with self.subTest(configuration=label):
                p = replace(ComponentParams(), low_technology=low, high_technology=high,
                            optimize_injection=False, use_subcooler=False)
                cycle = model.ciclo_cascata(p, 45)
                row = record(label, p, cycle)
                self.assertEqual(cycle["high"]["Q_sc"], 0)
                self.assertFalse(row["with_high_stage_subcooler"])
                self.assertAlmostEqual(cycle["Q_total"], 170000, places=5)
                self.assertLess(abs(row["energy_residual_W"]), 0.02)
                self.assertLess(abs(row["cascade_residual_W"]), 0.02)
                if high == "ejector":
                    self.assertGreater(cycle["high"]["Q_ihx"], 0)


if __name__ == "__main__":
    unittest.main()
