"""Runner reuse must preserve physics inputs, complete output, and resumability."""

import csv
import io
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from hthp import cli
from hthp.configurations import ARCHITECTURES, ComponentParams


def fake_cycle():
    """Only fields consumed by the mocked-output runner, not a physics result."""
    return dict(COP=2.4, T_cd_l=45.0, T_ev_h=40.0, W_total=170000 / 2.4,
                low=dict(P_int=None), high=dict(P_int=None))


def fake_evaluate(label, case, temperature):
    return dict(configuration=label, status="valid", COP=2 + temperature / 100
                + case.T_source_in / 1000,
                low_condensation_C=float(temperature),
                source_inlet_C=case.T_source_in,
                with_high_stage_subcooler=case.use_subcooler)


class RuntimeReuseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.root_patch = patch("hthp.cli.ROOT", self.root)
        self.root_patch.start()
        self.signature_patch = patch("hthp.calculation_cache._default_signature", return_value="test-equations-v1")
        self.signature_patch.start()
        self.addCleanup(self.signature_patch.stop)
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.directory.cleanup)

    def args(self, *arguments):
        args = cli.build_parser().parse_args(["--pontos", "3", *arguments])

        def close_cache():
            cache = getattr(args, "_calculation_cache", None)
            if cache is not None:
                cache.close()

        self.addCleanup(close_cache)
        return args

    def test_point_curve_and_ph_share_one_complete_optimum(self):
        args = self.args()
        p = ComponentParams(T_cd_l_step=args.tolerancia)
        cycle = fake_cycle()
        row = dict(configuration="Conventional cascade", status="valid", COP=2.4)
        with patch("hthp.cli.model.otimizar_cascata", return_value=(cycle, [])) as optimize, \
             patch("hthp.cli.model.T_cd_l_max", return_value=70), \
             patch("hthp.cli.evaluate", side_effect=fake_evaluate), \
             patch("hthp.cli.record", return_value=row), \
             patch("hthp.cli.plot_curves"), \
             patch("hthp.cli.ph_analysis") as ph, patch("builtins.print"):
            for analysis in ("ponto", "curva", "ph"):
                args.analise = analysis
                cli.run_selected_analysis("Conventional cascade", p, args)
        self.assertEqual(optimize.call_count, 1)
        self.assertEqual(ph.call_args.kwargs["cycles"], [cycle])
        for folder, filename in (("ponto", "result.csv"), ("curva", "curve.csv"),
                                 ("curva", "optimum.csv"), ("ph", "optimal_point.csv")):
            self.assertTrue((self.root / "results/cascata/conventional_cascade"
                             / folder / filename).exists())

    def test_full_optimum_is_reused_after_new_runner_arguments(self):
        p = ComponentParams()
        with patch("hthp.cli.model.otimizar_cascata", return_value=(fake_cycle(), [45])) as optimize:
            first = cli._cached_optimum(self.args(), p)
            resumed = cli._cached_optimum(self.args(), p)
        self.assertEqual(optimize.call_count, 1)
        self.assertEqual(first, resumed)

    def test_interrupted_map_resumes_only_missing_points(self):
        p = ComponentParams()
        args = self.args("--analise", "mapa")
        output = self.root / "map"
        calls = []

        def interrupted(label, case, temperature):
            calls.append((case.T_source_in, temperature))
            if len(calls) == 3:
                raise KeyboardInterrupt
            return fake_evaluate(label, case, temperature)

        with patch("hthp.cli.model.T_cd_l_max", return_value=70), \
             patch("hthp.cli.evaluate", side_effect=interrupted), patch("builtins.print"):
            with self.assertRaises(KeyboardInterrupt):
                cli.run_map("Conventional cascade", p, args, output)
        saved_points = set(calls[:2])
        resumed_calls = []

        def resumed(label, case, temperature):
            resumed_calls.append((case.T_source_in, temperature))
            return fake_evaluate(label, case, temperature)

        with patch("hthp.cli.model.T_cd_l_max", return_value=70), \
             patch("hthp.cli.evaluate", side_effect=resumed), \
             patch("hthp.cli.save_figure"), patch("builtins.print"):
            cli.run_map("Conventional cascade", p, self.args("--analise", "mapa"), output)
        self.assertEqual(len(resumed_calls), 7)
        self.assertTrue(saved_points.isdisjoint(resumed_calls))
        with (output / "map.csv").open(encoding="utf-8") as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 9)

    def test_every_physics_parameter_and_temperature_are_part_of_row_key(self):
        p = ComponentParams()
        args = self.args()
        variants = (p, replace(p, T_source_in=25), replace(p, Q_target=120000),
                    replace(p, use_subcooler=False), replace(p, T_cd_l_step=0.05),
                    replace(p, low_technology="flash_tank"))
        with patch("hthp.cli.evaluate", side_effect=fake_evaluate) as evaluate:
            for case in variants:
                cli._cached_evaluate(args, "case", case, 45.0)
            cli._cached_evaluate(args, "case", p, 46.0)
            self.assertEqual(evaluate.call_count, len(variants) + 1)
            for case in variants:
                cli._cached_evaluate(args, "case", case, 45.0)
            self.assertEqual(evaluate.call_count, len(variants) + 1)

    def test_changed_solver_signature_does_not_reuse_old_result(self):
        p = ComponentParams()
        with patch("hthp.cli.evaluate", side_effect=fake_evaluate) as evaluate:
            cli._cached_evaluate(self.args(), "case", p, 45)
            cli._cached_evaluate(self.args(), "case", p, 45)
            self.assertEqual(evaluate.call_count, 1)
            with patch("hthp.calculation_cache._default_signature", return_value="test-equations-v2"):
                cli._cached_evaluate(self.args(), "case", p, 45)
            self.assertEqual(evaluate.call_count, 2)

    def test_recalcular_refreshes_prior_run_but_reuses_fresh_results(self):
        p = ComponentParams()
        with patch("hthp.cli.evaluate", side_effect=fake_evaluate) as evaluate, \
             patch("hthp.cli.model.otimizar_cascata", return_value=(fake_cycle(), [])) as optimize:
            ordinary = self.args()
            cli._cached_evaluate(ordinary, "case", p, 45)
            cli._cached_optimum(ordinary, p)
            refreshed = self.args("--recalcular")
            cli._cached_evaluate(refreshed, "case", p, 45)
            cli._cached_optimum(refreshed, p)
            cli._cached_evaluate(refreshed, "case", p, 45)
            cli._cached_optimum(refreshed, p)
            self.assertEqual(evaluate.call_count, 2)
            self.assertEqual(optimize.call_count, 2)
            next_run = self.args()
            cli._cached_evaluate(next_run, "case", p, 45)
            cli._cached_optimum(next_run, p)
            self.assertEqual(evaluate.call_count, 2)
            self.assertEqual(optimize.call_count, 2)

    def test_all_still_dispatches_every_architecture_and_analysis(self):
        args = self.args("all")
        dispatches = []

        def selected(label, p, current):
            dispatches.append((label, p.low_technology, p.high_technology,
                               current.analise, p.Q_target, p.use_subcooler))

        with patch("hthp.cli.run_selected_analysis", side_effect=selected), \
             patch("hthp.cli.run_comparison") as comparison, \
             patch("hthp.component_comparison.run_component_comparison") as paired, \
             patch("builtins.print"):
            cli.run_all_architectures(args)
        self.assertEqual(len(dispatches), len(ARCHITECTURES) * 5)
        expected = [(label, low, high, analysis, 170000, True)
                    for label, low, high in ARCHITECTURES
                    for analysis in ("ponto", "curva", "ph", "mapa", "fonte")]
        self.assertEqual(dispatches, expected)
        comparison.assert_called_once()
        paired.assert_called_once()
        self.assertEqual(args.analise, "all")

    def test_interrupt_closes_storage_and_explains_forced_refresh_resume(self):
        for refresh in (False, True):
            with self.subTest(refresh=refresh):
                cache = Mock()

                def interrupted(label, p, args):
                    args._calculation_cache = cache
                    raise KeyboardInterrupt

                argv = ["--analise", "mapa"] + (["--recalcular"] if refresh else [])
                with patch("hthp.cli.run_selected_analysis", side_effect=interrupted), \
                     patch("sys.stderr", new_callable=io.StringIO) as stderr:
                    with self.assertRaises(SystemExit) as stopped:
                        cli.main(argv)
                self.assertEqual(stopped.exception.code, 130)
                cache.close.assert_called_once()
                expected = "sem --recalcular" if refresh else "repita o mesmo comando"
                self.assertIn(expected, stderr.getvalue())

    def test_replot_and_forced_refresh_cannot_be_combined(self):
        with patch("sys.stderr"), patch("hthp.cli.run_comparison") as run:
            with self.assertRaises(SystemExit):
                cli.main(["--analise", "comparacao", "--replotar", "--recalcular"])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
