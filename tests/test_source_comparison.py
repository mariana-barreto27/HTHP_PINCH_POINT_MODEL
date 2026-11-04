"""Source comparisons fix the coupling and use a matching conventional point."""

import csv
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hthp.cli import build_parser, main
from hthp.comparisons import comparison_views, relative_cop_groups
from hthp.configurations import ComponentParams
from hthp.source_comparison import run_source_comparison


class SourceComparisonTests(unittest.TestCase):
    def test_gains_match_source_not_constant_coupling_temperature(self):
        def rows(cops):
            return [dict(status="valid", source_inlet_C=t, low_condensation_C=45, COP=cop)
                    for t, cop in zip((5, 40), cops)]
        groups = [("reference", rows((2, 4))), ("other", rows((2.2, 4.8)))]
        gains = dict(relative_cop_groups(groups, "reference", xkey="source_inlet_C"))
        self.assertAlmostEqual(gains["other"][0]["COP_gain_percent"], 10)
        self.assertAlmostEqual(gains["other"][1]["COP_gain_percent"], 20)

    def test_fixed_coupling_separate_source_values_and_replot_without_solver(self):
        args = build_parser().parse_args(["--analise", "comparacao", "--grupo", "expansor",
                                         "--pontos", "3", "--comparar-fonte", "--temperatura-baixa", "45"])
        p = ComponentParams()
        views = comparison_views("expansor")
        calls = []
        def evaluate(label, case, temperature):
            calls.append((label, case, temperature))
            return dict(configuration=label, status="valid", source_inlet_C=case.T_source_in,
                        low_condensation_C=temperature,
                        COP=2 + case.T_source_in/100 + 0.1*(label != "Conventional cascade"))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch("hthp.source_comparison.evaluate", side_effect=evaluate), \
                 patch("hthp.source_comparison.plot_curves"), patch("builtins.print"):
                run_source_comparison(args, p, views, output)
            self.assertEqual(len(calls), 12)
            self.assertEqual({temperature for _, _, temperature in calls}, {45})
            self.assertEqual({case.T_source_in for _, case, _ in calls}, {5, 22.5, 40})
            self.assertTrue(all(case.Q_target == 170000 and case.use_subcooler for _, case, _ in calls))
            folder = output / "fonte/por_componente/expansor"
            with (folder / "cop_gains.csv").open() as stream:
                records = list(csv.DictReader(stream))
            baseline = [row for row in records if row["configuration"] == "Conventional cascade"]
            self.assertTrue(all(float(row["COP_gain_percent"]) == 0 for row in baseline))
            args.replotar = True
            with patch("hthp.source_comparison.evaluate", side_effect=AssertionError("must reuse")), \
                 patch("hthp.source_comparison.plot_curves"), patch("builtins.print"):
                run_source_comparison(args, p, views, output)
                args.temperatura_baixa = 50
                with self.assertRaisesRegex(ValueError, "incompatível"):
                    run_source_comparison(args, p, views, output)

    def test_cli_rejects_unsupported_combined_modes(self):
        with patch("sys.stderr"):
            for argv in (["--analise", "ponto", "--comparar-fonte"],
                         ["--analise", "comparacao", "--comparar-fonte", "--comparar-subcooler"]):
                with self.assertRaises(SystemExit):
                    main(argv)


if __name__ == "__main__":
    unittest.main()
