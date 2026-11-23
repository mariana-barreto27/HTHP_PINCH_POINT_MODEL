"""Comparação da temperatura da fonte com o acoplamento da cascata fixo."""

import csv
import json
from dataclasses import replace
from pathlib import Path

import numpy as np

from hthp.analyses import evaluate, plot_curves, save_rows
from hthp.comparisons import (comparison_metadata, relative_cop_groups,
                              solver_signature, view_cases)
from hthp.configurations import has_injection


def run_source_comparison(args, p, views, output):
    """Varia a fonte sem otimizar a temperatura de acoplamento."""
    from hthp.cli import _sweep_rows

    cases = view_cases(views)
    temperatures = np.linspace(5.0, 40.0, args.pontos)
    metadata = comparison_metadata(p, args.pontos, solver_signature(), cases)
    metadata.update(analysis="comparacao_fonte",
                    fixed_low_condensation_C=args.temperatura_baixa,
                    source_temperatures_C=temperatures.tolist())
    output = Path(output)
    saved_folder = output / "fonte" / views[0].folder
    if args.replotar:
        try:
            saved_conditions = json.loads((saved_folder / "conditions.json").read_text(encoding="utf-8"))
            with (saved_folder / "source_temperature_sweeps.csv").open(newline="", encoding="utf-8") as stream:
                saved_rows = list(csv.DictReader(stream))
        except (OSError, ValueError) as error:
            raise ValueError("Falta a comparação da fonte salva; execute sem --replotar.") from error
        if saved_conditions != metadata:
            raise ValueError("Comparação da fonte incompatível; execute sem --replotar.")
        groups = []
        for label, _, _ in cases:
            rows = [dict(row) for row in saved_rows if row["configuration"] == label]
            for row in rows:
                for key, value in row.items():
                    try:
                        row[key] = float(value)
                    except (ValueError, TypeError):
                        pass
                if row["status"] not in ("valid", "invalid"):
                    raise ValueError(f"Status inválido na curva de fonte: {label}")
                cop = row.get("COP")
                if row["status"] == "valid" and (not isinstance(cop, (int, float)) or not np.isfinite(cop)):
                    raise ValueError(f"COP incompleto na curva de fonte: {label}")
                if (not isinstance(row.get("source_inlet_C"), (int, float))
                        or not isinstance(row.get("low_condensation_C"), (int, float))):
                    raise ValueError(f"Temperaturas incompletas na curva de fonte: {label}")
            saved_temperatures = [row["source_inlet_C"] for row in rows]
            if len(saved_temperatures) != len(temperatures) or not np.allclose(saved_temperatures, temperatures, rtol=0, atol=1e-9):
                raise ValueError(f"Curva de fonte incompleta: {label}; recalcule.")
            for row in rows:
                if not np.isclose(float(row["low_condensation_C"]), args.temperatura_baixa):
                    raise ValueError(f"Temperatura de acoplamento incompatível: {label}; recalcule.")
            groups.append((label, rows))
        print(f"Reutilizando comparação da fonte: {saved_folder}", flush=True)
    else:
        groups = []
        for index, (label, low, high) in enumerate(cases, 1):
            print(f"Fonte {index}/{len(cases)}: {label}", flush=True)
            case = replace(p, low_technology=low, high_technology=high,
                           optimize_injection=any(has_injection(t) for t in (low, high)))
            points = ((replace(case, T_source_in=float(t)), args.temperatura_baixa)
                      for t in temperatures)
            rows = _sweep_rows(args, label, points, len(temperatures), "Fonte",
                               evaluator=evaluate)
            groups.append((label, rows))
    for view in views:
        labels = {case[0] for case in view.cases}
        subset = [(label, rows) for label, rows in groups if label in labels]
        destination = output / "fonte" / view.folder
        destination.mkdir(parents=True, exist_ok=True)
        conditions = dict(metadata, cases=[dict(configuration=label, low=low, high=high)
                                          for label, low, high in view.cases])
        (destination / "conditions.json").write_text(
            json.dumps(conditions, indent=2, ensure_ascii=False), encoding="utf-8")
        sweep_rows = []
        for _, rows in subset:
            sweep_rows.extend(rows)
        save_rows(sweep_rows, destination / "source_temperature_sweeps.csv")
        title = (f"{view.title}\nLow-stage condensation fixed at "
                 f"{args.temperatura_baixa:g} °C")
        plot_curves(subset, "source_inlet_C", "COP", "Heat-source inlet temperature [°C]",
                    "Overall COP [-]", title, destination / "cop_vs_heat_source_temperature", p)
        gains = relative_cop_groups(subset, view.reference, xkey="source_inlet_C")
        gain_rows = []
        for _, rows in gains:
            gain_rows.extend(rows)
        save_rows(gain_rows, destination / "cop_gains.csv")
        plot_curves(gains, "source_inlet_C", "COP_gain_percent", "Heat-source inlet temperature [°C]",
                    "COP change [%]", title.replace("Cascade COP", "Cascade COP change"),
                    destination / "cop_gain_vs_heat_source_temperature", p,
                    legend_title=f"Reference: {view.reference}\nAt the same source and coupling temperatures")
        print(f"Comparação da fonte: {destination}", flush=True)
