"""Mixed-stage selections, like-for-like plots and reusable result safeguards."""

from dataclasses import replace
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from hthp import model
from hthp.cli import build_parser, selected_case, run_comparison, case_folder
from hthp.comparisons import (comparison_views, view_cases, relative_cop_groups, compact_label,
                              comparison_metadata, load_comparison_data, solver_signature)
from hthp.configurations import (ARCHITECTURES, BASE_ARCHITECTURES,
                                 MIXED_ARCHITECTURES, EXPANDER_ARCHITECTURES,
                                 ComponentParams)
from hthp.plots.style import COLORS, DASHES, MARKERS


class ComparisonTests(unittest.TestCase):
    def test_registry_preserves_old_product_and_appends_three_expander_placements(self):
        technologies = ("simple", "flash_tank", "economizer", "ejector")
        legacy = BASE_ARCHITECTURES + MIXED_ARCHITECTURES
        self.assertEqual(ARCHITECTURES[:16], legacy)
        self.assertEqual({case[1:] for case in legacy}, set(itertools.product(technologies, repeat=2)))
        self.assertEqual(ARCHITECTURES[:10], BASE_ARCHITECTURES)
        self.assertEqual(len(MIXED_ARCHITECTURES), 6)
        self.assertEqual(ARCHITECTURES[16:], EXPANDER_ARCHITECTURES)
        self.assertEqual({case[1:] for case in EXPANDER_ARCHITECTURES},
                         {("simple", "expander"), ("expander", "simple"),
                          ("expander", "expander")})
        self.assertEqual(len({case[0] for case in ARCHITECTURES}), 19)
        self.assertEqual((len(COLORS), len(DASHES), len(MARKERS)), (19, 19, 19))

    def test_each_component_view_has_seven_component_cases_and_one_reference(self):
        for choice, technology in (("economizador", "economizer"),
                                   ("flash", "flash_tank"), ("ejetor", "ejector")):
            view, = comparison_views(choice)
            self.assertEqual(len(view.cases), 8)
            self.assertEqual(view.cases[0], ARCHITECTURES[0])
            self.assertTrue(all(technology in case[1:] for case in view.cases[1:]))

    def test_fixed_component_views_hold_component_not_temperature(self):
        views = comparison_views()
        self.assertEqual(len(views), 16)
        for view in views:
            if "componente_baixa_fixo" in view.folder:
                technology = view.cases[0][1]
                expected = {"simple": 5, "expander": 2}.get(technology, 4)
                self.assertEqual(len(view.cases), expected)
                self.assertEqual(len({case[1] for case in view.cases}), 1)
            if "componente_alta_fixo" in view.folder:
                technology = view.cases[0][2]
                expected = {"simple": 5, "expander": 2}.get(technology, 4)
                self.assertEqual(len(view.cases), expected)
                self.assertEqual(len({case[2] for case in view.cases}), 1)
            self.assertIn(view.reference, {case[0] for case in view.cases})
        self.assertEqual(view_cases(views), ARCHITECTURES)

    def test_explicit_cli_stages_keep_legacy_selection_working(self):
        parser = build_parser()
        label, p = selected_case(parser.parse_args(["--baixa", "flash", "--alta", "economizador"]))
        self.assertEqual((p.low_technology, p.high_technology), ("flash_tank", "economizer"))
        self.assertIn("high-stage economizer", label)
        folder = case_folder(label, parser.parse_args([]))
        self.assertEqual(folder.parent.name, "low-stage_flash_tank__high-stage_economizer")
        self.assertEqual(folder.parent.parent.name, "cascata")
        self.assertIn("IHX", compact_label(MIXED_ARCHITECTURES[3][0]))
        _, p = selected_case(parser.parse_args(["--alta", "ejetor"]))
        self.assertEqual((p.low_technology, p.high_technology), ("simple", "ejector"))
        _, p = selected_case(parser.parse_args(["--componente", "flash", "--estagio", "baixa"]))
        self.assertEqual((p.low_technology, p.high_technology), ("flash_tank", "simple"))
        with self.assertRaises(ValueError):
            selected_case(parser.parse_args(["--baixa", "flash", "--componente", "ejetor"]))

    def test_gains_use_the_same_temperature_and_preserve_missing_regions(self):
        groups = [("reference", [dict(status="valid", low_condensation_C=40, COP=2),
                                 dict(status="invalid", low_condensation_C=50)]),
                  ("other", [dict(status="valid", low_condensation_C=40, COP=2.2),
                             dict(status="valid", low_condensation_C=50, COP=3)])]
        gains = dict(relative_cop_groups(groups, "reference"))
        self.assertAlmostEqual(gains["other"][0]["COP_gain_percent"], 10)
        self.assertEqual(gains["other"][1]["status"], "invalid")
        self.assertEqual(groups[1][1][1]["status"], "valid")

    def fake_data(self, args):
        p = ComponentParams(T_cd_l_step=args.tolerancia)
        temperatures = np.linspace(p.T_cd_l_min, model.T_cd_l_max(p), args.pontos)
        summaries = []
        groups = []
        for index, (label, _, _) in enumerate(ARCHITECTURES):
            summaries.append(dict(configuration=label, status="valid", COP=2+index/100,
                                  low_condensation_C=45))
            groups.append((label, [dict(configuration=label, status="valid", COP=2+index/100,
                                        low_condensation_C=float(t), W_shaft_kW=80,
                                        low_discharge_C=90, high_discharge_C=140,
                                        low_minimum_efficiency=0.75, high_minimum_efficiency=0.72)
                                   for t in temperatures]))
        return p, summaries, groups, temperatures

    def test_output_views_and_replot_do_not_recompute_or_replace_legacy_cases(self):
        parser = build_parser()
        args = parser.parse_args(["--analise", "comparacao", "--pontos", "3"])
        p, summaries, groups, temperatures = self.fake_data(args)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch("hthp.cli._calculate_comparison_optima", return_value=summaries), \
                 patch("hthp.cli._calculate_architecture_curves", return_value=groups), \
                 patch("hthp.cli.plot_curves"), patch("builtins.print"):
                run_comparison(args, output)
            import csv
            with (output / "optima.csv").open() as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 10)
            legacy = (output / "optima.csv").read_bytes()
            with (output / "todas_combinacoes" / "optima.csv").open() as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), len(ARCHITECTURES))
            for view in comparison_views():
                self.assertTrue((output / view.folder / "cop_gains.csv").exists())
            args.grupo = "economizador"
            args.replotar = True
            with patch("hthp.cli._calculate_comparison_optima", side_effect=AssertionError("must reuse")), \
                 patch("hthp.cli._calculate_architecture_curves", side_effect=AssertionError("must reuse")), \
                 patch("hthp.cli.plot_curves"), patch("builtins.print"):
                run_comparison(args, output)
            self.assertEqual(legacy, (output / "optima.csv").read_bytes())
            expected = comparison_metadata(p, args.pontos, solver_signature(), ARCHITECTURES)
            expected["parameters"]["Q_target"] = 120000
            with self.assertRaisesRegex(ValueError, "parameters"):
                load_comparison_data(output / "todas_combinacoes", expected, ARCHITECTURES, temperatures)
            expected = comparison_metadata(p, args.pontos, "changed-equations", ARCHITECTURES)
            with self.assertRaisesRegex(ValueError, "solver_signature"):
                load_comparison_data(output / "todas_combinacoes", expected, ARCHITECTURES, temperatures)
            expected = comparison_metadata(p, args.pontos, solver_signature(), ARCHITECTURES)
            data = output / "todas_combinacoes" / "architecture_temperature_sweeps.csv"
            data.write_text(data.read_text().replace("high_discharge_C", "missing_temperature"))
            with self.assertRaisesRegex(ValueError, "high_discharge_C"):
                load_comparison_data(output / "todas_combinacoes", expected, ARCHITECTURES, temperatures)


class MixedPhysicsTests(unittest.TestCase):
    def test_all_six_mixed_connections_close_mass_energy_and_cascade(self):
        for label, low, high in MIXED_ARCHITECTURES:
            with self.subTest(configuration=label):
                p = replace(ComponentParams(), low_technology=low, high_technology=high,
                            optimize_injection=False)
                cycle = model.ciclo_cascata(p, 45)
                self.assertAlmostEqual(cycle["Q_total"], 170000, places=5)
                self.assertLess(abs(cycle["Q_total"]-cycle["W_total"]-cycle["low"]["Q_ev"]), 0.02)
                self.assertLess(abs(cycle["residual_cascade"]), 0.02)
                for stage, tech in (("low", low), ("high", high)):
                    result = cycle[stage]
                    if tech == "ejector":
                        self.assertIsNone(result["P_int"])
                        self.assertGreater(result["P_suction"], result["P_ev"])
                        self.assertLess(abs(result["separator_mass_residual"]), 1e-7)
                    else:
                        self.assertIsNotNone(result["P_int"])

    def test_injection_optimizer_does_not_treat_the_ejector_as_an_injection_port(self):
        p = replace(ComponentParams(), low_technology="flash_tank", high_technology="ejector")
        cycle = model.ciclo_cascata(p, 45)
        self.assertEqual(set(cycle["injection_search_fractions"]), {"injection_fraction_low"})
        self.assertIsNone(cycle["high"]["P_int"])
        self.assertAlmostEqual(cycle["Q_total"], 170000, places=5)


if __name__ == "__main__":
    unittest.main()
