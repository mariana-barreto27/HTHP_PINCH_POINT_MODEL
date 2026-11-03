"""Compare component additions against the same bare cascade reference."""

from dataclasses import asdict, replace
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hthp import model
from hthp.analyses import plot_curves, save_rows
from hthp.comparisons import (comparison_metadata, comparison_views,
                              load_comparison_data, relative_cop_groups,
                              solver_signature, view_cases)
from hthp.configurations import ComponentParams


def variant_label(label, with_subcooler):
    return label + (" + high-stage subcooler" if with_subcooler else " (no subcooler)")


def pair_results(data):
    """Keep both versions distinct in legends, tables and gain calculations."""
    summaries, groups = [], []
    for enabled, (variant_summaries, variant_groups) in data.items():
        for row in variant_summaries:
            item = dict(row, base_configuration=row["configuration"],
                        with_high_stage_subcooler=enabled)
            item["configuration"] = variant_label(row["configuration"], enabled)
            summaries.append(item)
        for label, rows in variant_groups:
            name = variant_label(label, enabled)
            converted = [dict(row, configuration=name, base_configuration=label,
                              with_high_stage_subcooler=enabled) for row in rows]
            groups.append((name, converted))
    return summaries, groups


def _variant_data(args, p, cases, views, output, signature):
    # Import only at call time: CLI owns the shared physics calculation helpers.
    from hthp.cli import _calculate_comparison_optima, _calculate_architecture_curves

    variant = "com_subcooler" if p.use_subcooler else "sem_subcooler"
    metadata = comparison_metadata(p, args.pontos, signature, cases)
    temperatures = np.linspace(p.T_cd_l_min, model.T_cd_l_max(p), args.pontos)
    comparison_root = output.parent
    candidates = [output / "dados" / variant / "todas_combinacoes",
                  output / "dados" / variant / views[0].folder,
                  comparison_root / "todas_combinacoes",
                  comparison_root / views[0].folder]
    failures = []
    for source in dict.fromkeys(candidates):
        try:
            summaries, groups = load_comparison_data(source, metadata, cases, temperatures)
            for row in [*summaries, *(row for _, rows in groups for row in rows)]:
                if row["status"] == "invalid" and "with_high_stage_subcooler" not in row:
                    continue  # An old failed optimum has no calculated state record.
                if row.get("with_high_stage_subcooler") not in (p.use_subcooler, str(p.use_subcooler)):
                    raise ValueError("Subcooler não identificado corretamente nos dados salvos.")
            print(f"Reutilizando {variant}: {source}", flush=True)
            return summaries, groups
        except (OSError, ValueError, KeyError) as error:
            failures.append(str(error))
    if args.replotar:
        raise ValueError(f"Faltam resultados compatíveis {variant}. "
                         "Execute sem --replotar. " + failures[-1])
    print(f"Calculando versões {variant} ({len(cases)} configurações)", flush=True)
    # An 'all' run cache belongs to only ONE subcooler setting.
    options = dict(vars(args))
    if p.use_subcooler != args.subcooler:
        options.pop("_optima_cache", None)
        options.pop("_curve_cache", None)
    options["subcooler"] = p.use_subcooler
    variant_args = SimpleNamespace(**options)
    summaries = [dict(row, with_high_stage_subcooler=p.use_subcooler)
                 for row in _calculate_comparison_optima(variant_args, p, cases)]
    groups = _calculate_architecture_curves(variant_args, p, cases)
    destination = output / "dados" / variant / views[0].folder
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "conditions.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    save_rows(summaries, destination / "optima.csv")
    save_rows([row for _, rows in groups for row in rows],
              destination / "architecture_temperature_sweeps.csv")
    return summaries, groups


def run_component_comparison(args, output):
    """Two actual calculations per architecture, never just relabel a curve."""
    output = Path(output)
    # The full and family figures explain additions without duplicating the
    # existing fixed-stage views. Every figure uses the same bare reference.
    views = tuple(view for view in comparison_views(args.grupo)
                  if not view.folder.startswith(("componente_baixa_fixo/", "componente_alta_fixo/")))
    cases = view_cases(views)
    p = ComponentParams(Q_target=args.carga*1000, T_source_in=args.fonte,
                        T_cd_l_step=args.tolerancia,
                        expander_isentropic_efficiency=args.eficiencia_expansor,
                        expander_recovery_efficiency=args.recuperacao_expansor)
    signature = solver_signature()
    data = {enabled: _variant_data(args, replace(p, use_subcooler=enabled), cases,
                                   views, output, signature) for enabled in (False, True)}
    summaries, groups = pair_results(data)
    reference = variant_label("Conventional cascade", False)
    for view in views:
        labels = {case[0] for case in view.cases}
        subset = [(name, rows) for name, rows in groups if rows[0]["base_configuration"] in labels]
        summary = [row for row in summaries if row["base_configuration"] in labels]
        summary.sort(key=lambda row: (row["status"] != "valid", -float(row.get("COP") or 0)))
        destination = output / view.folder
        destination.mkdir(parents=True, exist_ok=True)
        technologies = {label: (low, high) for label, low, high in view.cases}
        case_parameters = []
        for row in summary:
            low, high = technologies[row["base_configuration"]]
            case = replace(p, low_technology=low, high_technology=high,
                           use_subcooler=row["with_high_stage_subcooler"],
                           optimize_injection=any(t in ("flash_tank", "economizer") for t in (low, high)))
            case_parameters.append(dict(configuration=row["configuration"], parameters=asdict(case)))
        metadata = comparison_metadata(p, args.pontos, signature, view.cases)
        metadata.update(subcooler_comparison=True, reference=reference,
                        gain_comparison="same low-stage condensation temperature",
                        line_styles={"solid": "with high-stage subcooler",
                                     "dashed": "without high-stage subcooler"},
                        case_parameters=case_parameters)
        (destination / "conditions.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        save_rows(summary, destination / "optima.csv")
        save_rows([row for _, rows in subset for row in rows],
                  destination / "architecture_temperature_sweeps.csv")
        plot_curves(subset, "low_condensation_C", "COP",
                    "Low-stage condensation temperature [°C]", "Overall COP [-]",
                    view.title, destination / "cop_vs_low_stage_condensation", p,
                    subcooler_comparison=True)
        gains = relative_cop_groups(subset, reference)
        save_rows([row for _, rows in gains for row in rows], destination / "cop_gains.csv")
        plot_curves(gains, "low_condensation_C", "COP_gain_percent",
                    "Low-stage condensation temperature [°C]", "COP change [%]",
                    view.title.replace("Cascade COP", "Cascade COP change"),
                    destination / "cop_gain_vs_low_stage_condensation", p,
                    legend_title="Reference: conventional cascade without subcooler\nAt the same intermediate temperature",
                    subcooler_comparison=True)
        print(f"Comparação de adição de componentes: {destination}", flush=True)
    valid = [row for row in summaries if row["status"] == "valid"]
    if not valid:
        raise ValueError("Nenhuma combinação viável na comparação de componentes.")
    best = max(valid, key=lambda row: float(row["COP"]))
    print(f"Maior COP neste grupo: {best['configuration']} | {float(best['COP']):.4f}")
