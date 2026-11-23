"""Optimum summaries preserve cases and distinguish own-optimum comparisons."""

from copy import deepcopy
import csv
from pathlib import Path
import tempfile
import unittest

from hthp.configurations import (ARCHITECTURES, EXPANDER_HYBRID_ARCHITECTURES,
                                 ComponentParams)
from hthp.optimum_report import (STAGE_NAMES, build_optimum_summary,
                                 save_optimum_report, save_combined_optima_report)
from unittest.mock import patch


class OptimumReportTests(unittest.TestCase):
    def setUp(self):
        self.p = ComponentParams(T_cd_l_step=0.1)

    def row(self, label, cop, temperature=45, subcooler=True):
        return dict(configuration=label, status="valid", COP=cop,
                    low_condensation_C=temperature, high_evaporation_C=temperature-5,
                    W_net_shaft_kW=170/float(cop), W_recovered_kW=0,
                    with_high_stage_subcooler=subcooler)

    def test_all_supported_unique_cases_and_original_rows_unchanged(self):
        inputs = [self.row(label, 2 + index/100) for index, (label, _, _) in enumerate(ARCHITECTURES)]
        before = deepcopy(inputs)
        rows = build_optimum_summary(inputs, self.p)
        self.assertEqual(len(rows), len(ARCHITECTURES))
        self.assertEqual(len({row["base_configuration"] for row in rows}), len(ARCHITECTURES))
        for label, low, high in EXPANDER_HYBRID_ARCHITECTURES:
            row = next(row for row in rows if row["base_configuration"] == label)
            self.assertEqual((row["low_component"], row["high_component"]), (low, high))
        self.assertEqual(rows[0]["base_configuration"], ARCHITECTURES[-1][0])
        self.assertEqual(inputs, before)
        baseline = next(row for row in rows if row["configuration"] == "Conventional cascade")
        self.assertEqual(baseline["COP_gain_at_own_optimum_percent"], 0)

    def test_numeric_strings_and_different_own_optimum_temperatures(self):
        baseline = self.row("Conventional cascade", "2", temperature=60)
        other = self.row("High-stage expander", "2.5", temperature=45)
        other.update(low_condensation_C="45", high_evaporation_C="40",
                     W_net_shaft_kW="68", W_recovered_kW="5",
                     with_high_stage_subcooler="True")
        rows = build_optimum_summary([baseline, other], self.p)
        self.assertEqual(rows[0]["COP_gain_at_own_optimum_percent"], 25)
        self.assertEqual(rows[0]["W_net_shaft_kW"], 68)
        self.assertEqual(rows[0]["low_condensation_optimum_C"], 45)
        self.assertEqual(rows[0]["high_stage"], "Expansor")

    def test_paired_references_use_matching_subcooler_and_base_labels(self):
        summaries = [self.row("Conventional cascade", 2, subcooler=False),
                     self.row("Conventional cascade", 2.5, subcooler=True),
                     self.row("High-stage expander", 3, subcooler=True)]
        for row in summaries:
            row["base_configuration"] = row["configuration"]
            row["configuration"] += " + high-stage subcooler" if row["with_high_stage_subcooler"] else " (no subcooler)"
        rows = build_optimum_summary(summaries, self.p)
        self.assertAlmostEqual(rows[0]["COP_gain_at_own_optimum_percent"], 20)
        self.assertEqual(rows[0]["high_stage"], "Expansor")

    def test_invalid_and_missing_metrics_are_preserved_without_fake_zero(self):
        invalid = dict(configuration="Low-stage expander", status="invalid", reason="Sem ponto viável")
        missing = dict(configuration="High-stage expander", status="valid", COP="nan")
        valid = self.row("Expanders in both stages", 2.5)
        valid.pop("W_net_shaft_kW")
        rows = build_optimum_summary([invalid, missing, valid], self.p)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["status"], "valid")
        self.assertIsNone(rows[0]["W_net_shaft_kW"])
        self.assertIsNone(rows[0]["COP_gain_at_own_optimum_percent"])
        self.assertTrue(all(row["reason"] for row in rows[1:]))
        self.assertTrue(all(row["COP_max"] is None for row in rows[1:]))

    def test_boundary_flags_are_explicit_only_and_duplicate_cases_fail(self):
        baseline = self.row("Conventional cascade", 2)
        baseline["optimum_at_boundary"] = True
        rows = build_optimum_summary([baseline], self.p)
        self.assertIs(rows[0]["optimum_at_boundary"], True)
        self.assertNotIn("optimization_boundary", rows[0])
        with self.assertRaisesRegex(ValueError, "duplicada"):
            build_optimum_summary([baseline, dict(baseline)], self.p)

    def test_reports_have_all_rows_and_clear_assumption_and_gain_notes(self):
        summaries = [self.row(label, 2 + index/100) for index, (label, _, _) in enumerate(ARCHITECTURES)]
        summaries[-1] = dict(configuration=ARCHITECTURES[-1][0], status="invalid", reason="Teste & falha")
        with tempfile.TemporaryDirectory() as directory:
            rows = save_optimum_report(summaries, self.p, directory)
            output = Path(directory)
            self.assertEqual(len(rows), len(ARCHITECTURES))
            self.assertTrue((output / "optima_summary.csv").exists())
            self.assertFalse((output / "optima.csv").exists())
            markdown = (output / "optima_summary.md").read_text()
            latex = (output / "optima_summary.tex").read_text()
            self.assertIn("COP máximo convencional", markdown)
            self.assertIn("Nos gráficos de ganho", markdown)
            self.assertIn("eficiência isentrópica = 0.5", markdown)
            self.assertIn("somente no estágio de alta", markdown)
            self.assertIn("Teste & falha", markdown)
            self.assertIn(r"\begin{tabular}", latex)
            self.assertNotIn(r"\begin{document}", latex)
            self.assertIn(r"\\{[°C]}", latex)
            self.assertNotIn(r"\\[°C]", latex)  # Would be parsed as a vertical-spacing dimension.
            self.assertEqual(sum(" & " in line and line.endswith(r"\\") for line in latex.splitlines()),
                             len(ARCHITECTURES) + 1)

    def test_all_expander_hybrids_keep_both_stage_names_in_csv_and_latex(self):
        summaries = [self.row("Conventional cascade", 2)]
        summaries += [self.row(label, 2.5 + index/100)
                      for index, (label, _, _) in enumerate(EXPANDER_HYBRID_ARCHITECTURES)]
        with tempfile.TemporaryDirectory() as directory:
            save_optimum_report(summaries, self.p, directory)
            output = Path(directory)
            with (output / "optima_summary.csv").open(newline="", encoding="utf-8") as stream:
                rows = {row["base_configuration"]: row for row in csv.DictReader(stream)}
            for label, low, high in EXPANDER_HYBRID_ARCHITECTURES:
                self.assertEqual((rows[label]["low_component"], rows[label]["high_component"]),
                                 (low, high))
                self.assertEqual(rows[label]["status"], "valid")
            latex = (output / "optima_summary.tex").read_text(encoding="utf-8")
            self.assertIn("Expansor & Flash tank", latex)
            self.assertIn("Flash tank & Expansor", latex)
            for _, low, high in EXPANDER_HYBRID_ARCHITECTURES:
                self.assertIn(f"{STAGE_NAMES[low]} & {STAGE_NAMES[high]}", latex)

    def test_combined_table_requires_all_actual_subcooler_versions(self):
        summaries = [self.row(label, 2 + index/100 + 0.1*enabled, subcooler=enabled)
                     for enabled in (False, True) for index, (label, _, _) in enumerate(ARCHITECTURES)]
        with tempfile.TemporaryDirectory() as directory, \
             patch("hthp.optimum_report.render_optimum_table"):
            rows = save_combined_optima_report(summaries, self.p, directory, "signature")
            expected_count = 2 * len(ARCHITECTURES)
            self.assertEqual(len(rows), expected_count)
            import json
            metadata = json.loads((Path(directory) / "conditions.json").read_text())
            self.assertEqual(metadata["case_count"], expected_count)
            identities = {(row["base_configuration"], row["with_high_stage_subcooler"])
                          for row in rows}
            for label, low, high in EXPANDER_HYBRID_ARCHITECTURES:
                for enabled in (False, True):
                    self.assertIn((label, enabled), identities)
                    row = next(row for row in rows if row["base_configuration"] == label
                               and row["with_high_stage_subcooler"] == enabled)
                    self.assertEqual((row["low_component"], row["high_component"]), (low, high))
            self.assertFalse(metadata["parameters_by_subcooler"]["False"]["use_subcooler"])
            self.assertTrue(metadata["parameters_by_subcooler"]["True"]["use_subcooler"])
            self.assertEqual(metadata["solver_signature"], "signature")
            with self.assertRaisesRegex(ValueError, f"{expected_count} casos"):
                save_combined_optima_report(summaries[:-1], self.p, directory, "signature")


if __name__ == "__main__":
    unittest.main()
