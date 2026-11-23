"""Agrupamento das arquiteturas e leitura dos resultados para comparação."""

import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

import CoolProp
import numpy as np
import scipy

from hthp.configurations import (ARCHITECTURES, MIXED_ARCHITECTURES,
                                 EXPANDER_HYBRID_ARCHITECTURES,
                                 LEGACY_ARCHITECTURES, INTRASTAGE_ARCHITECTURES,
                                 INTRASTAGE_TECHNOLOGIES, technology_components)


TECHNOLOGY_NAMES = {
    "simple": "conventional cycle", "flash_tank": "flash tank",
    "economizer": "economizer", "ejector": "ejector + IHX",
    "expander": "expander",
}
TECHNOLOGY_FOLDERS = {
    "simple": "simples", "flash_tank": "flash_tank",
    "economizer": "economizador", "ejector": "ejetor_ihx",
    "expander": "expansor",
}
TECHNOLOGY_NAMES.update({key: value[0] for key, value in INTRASTAGE_TECHNOLOGIES.items()})
TECHNOLOGY_FOLDERS.update({key: key for key in INTRASTAGE_TECHNOLOGIES})

INTRASTAGE_GROUPS = {
    "flash-expansor": ("flash_expansor", "flash tank + expander", {"flash_tank", "expander"}),
    "economizador-expansor": ("economizador_expansor", "economizer + expander", {"economizer", "expander"}),
    "ejetor-expansor": ("ejetor_expansor", "ejector + expander", {"ejector", "expander"}),
    "flash-ejetor": ("flash_ejetor", "flash tank + ejector", {"flash_tank", "ejector"}),
    "economizador-ejetor": ("economizador_ejetor", "economizer + ejector", {"economizer", "ejector"}),
}


def _intrastage_views():
    views = []
    for folder, title, members in INTRASTAGE_GROUPS.values():
        # Compara a combinação no mesmo circuito com cada componente isolado.
        baseline = []
        for case in LEGACY_ARCHITECTURES:
            stages = set(case[1:])
            if stages <= members | {"simple"} and len(stages - {"simple"}) <= 1:
                baseline.append(case)

        hybrids = []
        for case in INTRASTAGE_ARCHITECTURES:
            for technology in case[1:]:
                if technology_components(technology) == members:
                    hybrids.append(case)
                    break
        views.append(ComparisonView(f"mesmo_circuito/{folder}",
                                    f"Cascade COP — within-circuit {title}",
                                    tuple(baseline + hybrids), all_metrics=True))
    return tuple(views)


@dataclass(frozen=True)
class ComparisonView:
    folder: str
    title: str
    cases: tuple
    reference: str = "Conventional cascade"
    all_metrics: bool = False


def comparison_views(group="todos"):
    if group == "turbina":
        group = "expansor"
    conventional = ARCHITECTURES[0]
    intrastage = _intrastage_views()
    if group == "mesmo-ciclo":
        return intrastage
    if group in INTRASTAGE_GROUPS:
        folder = INTRASTAGE_GROUPS[group][0]
        return tuple(view for view in intrastage if view.folder.endswith("/" + folder))
    family_views = {}
    for technology, choice, title in (
        ("economizer", "economizador", "economizer configurations"),
        ("flash_tank", "flash", "flash-tank configurations"),
        ("ejector", "ejetor", "ejector + IHX configurations"),
        ("expander", "expansor", "expansion work recovery"),
    ):
        cases = [conventional]
        for case in ARCHITECTURES:
            _, low, high = case
            if (technology in technology_components(low)
                    or technology in technology_components(high)):
                cases.append(case)
        family_views[choice] = ComparisonView(
            f"por_componente/{TECHNOLOGY_FOLDERS[technology]}",
            f"Cascade COP — {title}", tuple(cases),
            all_metrics=True)
    mixed = ComparisonView("combinacoes_mistas", "Cascade COP — mixed configurations",
                           (conventional,) + MIXED_ARCHITECTURES + EXPANDER_HYBRID_ARCHITECTURES,
                           all_metrics=True)
    if group == "mistas":
        return (mixed,)
    if group in family_views:
        return (family_views[group],)
    if group != "todos":
        raise ValueError(f"Grupo de comparação desconhecido: {group}")
    views = [ComparisonView("todas_combinacoes", "Cascade COP — all supported configurations",
                            ARCHITECTURES, all_metrics=True), *family_views.values(), mixed,
             *intrastage]
    for stage_index, stage, folder in ((1, "Low", "componente_baixa_fixo"),
                                      (2, "High", "componente_alta_fixo")):
        for technology in ("simple", "flash_tank", "economizer", "ejector", "expander"):
            name = TECHNOLOGY_NAMES[technology]
            cases = tuple(case for case in ARCHITECTURES if case[stage_index] == technology)
            other_stage_index = 3 - stage_index
            reference = next(case[0] for case in cases if case[other_stage_index] == "simple")
            views.append(ComparisonView(
                f"{folder}/{TECHNOLOGY_FOLDERS[technology]}",
                f"Cascade COP — {stage.lower()} stage: {name}", cases, reference,
                all_metrics=True))
    return tuple(views)


def view_cases(views):
    labels = set()
    for view in views:
        for label, _, _ in view.cases:
            labels.add(label)
    return tuple(case for case in ARCHITECTURES if case[0] in labels)


def compact_label(label):
    """Encurta a legenda sem perder a identificação dos estágios."""
    if " / " not in label:
        return label
    case = next((case for case in ARCHITECTURES if case[0] == label), None)
    if case is None:
        return label
    low_name = TECHNOLOGY_NAMES[case[1]]
    low_name = low_name[:1].upper() + low_name[1:]
    return (f"{low_name} (low) / "
            f"{TECHNOLOGY_NAMES[case[2]]} (high)")


def relative_cop_groups(groups, reference, xkey="low_condensation_C"):
    """Calcula o ganho de COP em relação à referência na mesma temperatura."""
    reference_rows = dict(groups)[reference]
    reference_by_temperature = {round(float(row[xkey]), 9): row for row in reference_rows}
    result = []
    for label, rows in groups:
        converted = []
        for row in rows:
            result_row = dict(row)
            reference_row = reference_by_temperature.get(round(float(row[xkey]), 9))
            if (row["status"] == "valid" and reference_row is not None
                    and reference_row["status"] == "valid" and float(reference_row["COP"]) > 0):
                result_row["COP_gain_percent"] = 100 * (float(row["COP"])/float(reference_row["COP"]) - 1)
            else:
                result_row["status"] = "invalid"
                result_row["COP_gain_percent"] = float("nan")
            converted.append(result_row)
        result.append((label, converted))
    return result


def solver_signature():
    """Identifica a versão dos cálculos e das bibliotecas de propriedades."""
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
    """Lê os CSVs salvos e confere os parâmetros, as métricas e a malha."""
    folder = Path(folder)
    metadata = json.loads((folder / "conditions.json").read_text(encoding="utf-8"))
    for key in ("parameters", "points", "solver_signature"):
        if metadata.get(key) != expected[key]:
            raise ValueError(f"Resultados salvos incompatíveis ({key}); gere a comparação novamente.")
    with (folder / "architecture_temperature_sweeps.csv").open(newline="") as stream:
        raw_rows = list(csv.DictReader(stream))
    needs_recovery_metrics = False
    for _, low, high in cases:
        if ("expander" in technology_components(low)
                or "expander" in technology_components(high)):
            needs_recovery_metrics = True
            break
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
                if needs_recovery_metrics:
                    required += ("W_net_shaft_kW", "W_compressor_shaft_kW",
                                 "W_expander_shaft_kW", "W_recovered_kW", "W_recovery_loss_kW")
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
