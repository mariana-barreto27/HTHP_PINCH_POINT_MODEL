"""Views of the same calculated cascade cases; no thermodynamic changes."""

import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

import CoolProp
import numpy as np
import scipy

from hthp.configurations import ARCHITECTURES, MIXED_ARCHITECTURES


TECHNOLOGY_NAMES = {
    "simple": "conventional cycle", "flash_tank": "flash tank",
    "economizer": "economizer", "ejector": "ejector + IHX",
}
TECHNOLOGY_FOLDERS = {
    "simple": "simples", "flash_tank": "flash_tank",
    "economizer": "economizador", "ejector": "ejetor_ihx",
}


@dataclass(frozen=True)
class ComparisonView:
    folder: str
    title: str
    cases: tuple
    reference: str = "Conventional cascade"
    all_metrics: bool = False


def comparison_views(group="todos"):
    conventional = ARCHITECTURES[0]
    family_views = {}
    for technology, choice, title in (
        ("economizer", "economizador", "economizer configurations"),
        ("flash_tank", "flash", "flash-tank configurations"),
        ("ejector", "ejetor", "ejector + IHX configurations"),
    ):
        cases = (conventional,) + tuple(
            case for case in ARCHITECTURES if technology in case[1:])
        family_views[choice] = ComparisonView(
            f"por_componente/{TECHNOLOGY_FOLDERS[technology]}",
            f"Cascade COP — {title}", cases)
    mixed = ComparisonView("combinacoes_mistas", "Cascade COP — mixed configurations",
                           (conventional,) + MIXED_ARCHITECTURES)
    if group == "mistas":
        return (mixed,)
    if group in family_views:
        return (family_views[group],)
    if group != "todos":
        raise ValueError(f"Grupo de comparação desconhecido: {group}")
    views = [ComparisonView("todas_combinacoes", "Cascade COP — all component combinations",
                            ARCHITECTURES, all_metrics=True), *family_views.values(), mixed]
    for index, stage, folder in ((1, "Low", "componente_baixa_fixo"),
                                 (2, "High", "componente_alta_fixo")):
        for technology, name in TECHNOLOGY_NAMES.items():
            cases = tuple(case for case in ARCHITECTURES if case[index] == technology)
            reference = next(case[0] for case in cases if case[3-index] == "simple")
            views.append(ComparisonView(
                f"{folder}/{TECHNOLOGY_FOLDERS[technology]}",
                f"Cascade COP — {stage.lower()} stage: {name}", cases, reference))
    return tuple(views)


def view_cases(views):
    labels = {case[0] for view in views for case in view.cases}
    return tuple(case for case in ARCHITECTURES if case[0] in labels)


def compact_label(label):
    """Keep long mixed-case legends readable, with stages unambiguous."""
    if " / " not in label:
        return label
    case = next((case for case in ARCHITECTURES if case[0] == label), None)
    if case is None:
        return label
    low_name = TECHNOLOGY_NAMES[case[1]]
    low_name = low_name[:1].upper() + low_name[1:]
    return (f"{low_name} (low) / "
            f"{TECHNOLOGY_NAMES[case[2]]} (high)")


def relative_cop_groups(groups, reference):
    """Compare at the same temperature, NEVER compare separately optimized COPs."""
    rows_by_label = dict(groups)
    reference_rows = rows_by_label[reference]
    baseline = {round(float(row["low_condensation_C"]), 9): row
                for row in reference_rows}
    result = []
    for label, rows in groups:
        converted = []
        for row in rows:
            item = dict(row)
            base = baseline.get(round(float(row["low_condensation_C"]), 9))
            if (row["status"] == "valid" and base is not None
                    and base["status"] == "valid" and float(base["COP"]) > 0):
                item["COP_gain_percent"] = 100 * (float(row["COP"])/float(base["COP"]) - 1)
            else:
                item["status"] = "invalid"
                item["COP_gain_percent"] = float("nan")
            converted.append(item)
        result.append((label, converted))
    return result


def solver_signature():
    """Invalidate reusable data when equations, settings or property libraries change."""
    root = Path(__file__).parent
    files = [root / "model.py", root / "configurations.py"]
    for folder in ("components", "cycles", "thermo", "heat_sources"):
        files.extend(sorted((root / folder).rglob("*.py")))
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    digest.update(f"CoolProp={CoolProp.__version__};scipy={scipy.__version__}".encode())
    return digest.hexdigest()


def comparison_metadata(p, points, signature, cases):
    return dict(analysis="comparacao", parameters=asdict(p), points=points,
                solver_signature=signature,
                cases=[dict(configuration=label, low=low, high=high)
                       for label, low, high in cases])


def load_comparison_data(folder, expected, cases, temperatures):
    """Only explicitly requested, matching, complete CSVs can be replotted."""
    folder = Path(folder)
    metadata = json.loads((folder / "conditions.json").read_text(encoding="utf-8"))
    for key in ("parameters", "points", "solver_signature"):
        if metadata.get(key) != expected[key]:
            raise ValueError(f"Resultados salvos incompatíveis ({key}); gere a comparação novamente.")
    with (folder / "architecture_temperature_sweeps.csv").open(newline="") as stream:
        raw_rows = list(csv.DictReader(stream))
    groups = []
    for label, _, _ in cases:
        rows = []
        for raw in raw_rows:
            if raw["configuration"] != label:
                continue
            row = dict(raw)
            for key, value in row.items():
                if value in ("True", "False"):
                    row[key] = value == "True"
                elif value:
                    try:
                        row[key] = float(value)
                    except ValueError:
                        pass
            if row["status"] not in ("valid", "invalid"):
                raise ValueError(f"Status de resultado inválido: {label}")
            if row["status"] == "valid":
                required = ("COP", "W_shaft_kW", "low_discharge_C", "high_discharge_C",
                            "low_minimum_efficiency", "high_minimum_efficiency")
                for key in required:
                    try:
                        complete = math.isfinite(float(row[key]))
                    except (KeyError, ValueError, TypeError):
                        complete = False
                    if not complete:
                        raise ValueError(f"Resultado incompleto ({key}): {label}; recalcule.")
            rows.append(row)
        actual = [row["low_condensation_C"] for row in rows]
        if len(actual) != len(temperatures) or not np.allclose(actual, temperatures, rtol=0, atol=1e-9):
            raise ValueError(f"Curva ausente ou incompleta: {label}; gere a comparação novamente.")
        groups.append((label, rows))
    with (folder / "optima.csv").open(newline="") as stream:
        summaries = [row for row in csv.DictReader(stream)
                     if row["configuration"] in {case[0] for case in cases}]
    if {row["configuration"] for row in summaries} != {case[0] for case in cases}:
        raise ValueError("Tabela de ótimos incompleta; gere a comparação novamente.")
    for row in summaries:
        if row["status"] == "valid":
            row["COP"] = float(row["COP"])
            row["low_condensation_C"] = float(row["low_condensation_C"])
            if not math.isfinite(row["COP"]) or not math.isfinite(row["low_condensation_C"]):
                raise ValueError("Tabela de ótimos com valores não finitos; recalcule.")
    return summaries, groups
