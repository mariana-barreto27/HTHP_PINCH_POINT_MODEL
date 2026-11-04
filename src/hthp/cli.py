"""Command-line entry point for one heat-pump case at a time."""

import argparse
from dataclasses import asdict, replace
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache" / "matplotlib"))
os.environ.setdefault("MPLBACKEND", "Agg")

import numpy as np

from hthp import model
from hthp.analyses import evaluate, ph_analysis, plot_curves, record, save_rows
from hthp.configurations import ARCHITECTURES, BASE_ARCHITECTURES, ComponentParams
from hthp.comparisons import (comparison_views, view_cases, relative_cop_groups,
                              comparison_metadata, load_comparison_data, solver_signature)
from hthp.plots.style import MM, add_minor_grid, save_figure
from hthp.plots.heatmap import heatmap
from hthp.optimum_report import save_optimum_report


TECHNOLOGY = {
    "simples": "simple", "flash": "flash_tank", "economizador": "economizer",
    "ejetor": "ejector",
    "expansor": "expander", "turbina": "expander",
}
LABEL = {"simple": "simple", "flash_tank": "flash_tank", "economizer": "economizer",
         "ejector": "ejector_ihx", "expander": "expansor"}


def _unit_fraction(value):
    number = float(value)
    if not np.isfinite(number) or not 0.0 <= number <= 1.0:
        raise argparse.ArgumentTypeError("use um valor finito entre 0 e 1")
    return number


def _expander_options(args):
    return dict(expander_isentropic_efficiency=args.eficiencia_expansor,
                expander_recovery_efficiency=args.recuperacao_expansor)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python run.py",
        description="Roda uma análise da configuração de bomba de calor escolhida.",
        epilog=("Exemplo: python run.py --ciclo cascata --componente economizador "
                "--estagio ambos --analise ph"),
    )
    parser.add_argument("command", nargs="?", choices=("all",),
                        help="gera todas as análises para todas as arquiteturas da cascata")
    parser.add_argument("--ciclo", choices=("cascata", "alta"), default="cascata",
                        help="cascata completa ou apenas o estágio de alta")
    parser.add_argument("--componente", choices=tuple(TECHNOLOGY), default="simples",
                        help="componente aplicado ao(s) estágio(s) escolhido(s)")
    parser.add_argument("--estagio", choices=("baixa", "alta", "ambos"), default="ambos",
                        help="estágio que recebe o componente selecionado, incluindo expansor")
    parser.add_argument("--baixa", choices=tuple(TECHNOLOGY),
                        help="componente da baixa; use com --alta para uma combinação mista")
    parser.add_argument("--alta", choices=tuple(TECHNOLOGY),
                        help="componente da alta; o estágio não informado fica simples")
    parser.add_argument("--analise", choices=("ponto", "curva", "ph", "mapa", "fonte", "comparacao", "all"),
                        default="ponto", help="resultado que será calculado")
    subcooler = parser.add_mutually_exclusive_group()
    subcooler.add_argument("--subcooler", dest="subcooler", action="store_true",
                           help="inclui o subcooler do estágio de alta (padrão)")
    subcooler.add_argument("--sem-subcooler", dest="subcooler", action="store_false",
                           help="retira o subcooler")
    parser.set_defaults(subcooler=True)
    parser.add_argument("--carga", type=float, default=170.0, help="carga útil em kW")
    parser.add_argument("--fonte", type=float, default=30.0, help="temperatura de entrada da fonte em °C")
    parser.add_argument("--pontos", type=int, default=17, help="número de pontos em curvas e mapas")
    parser.add_argument("--tolerancia", type=float, default=0.1,
                        help="tolerância em °C da busca scipy.optimize pelo ponto ótimo")
    parser.add_argument("--temperatura-baixa", type=float, default=45.0,
                        help="condensação do estágio de baixa fixa nas análises de fonte/mapa")
    parser.add_argument("--eficiencia-expansor", type=_unit_fraction, default=0.50,
                        help="eficiência isentrópica do expansor [0–1]; 0 reproduz a válvula (padrão: 0.50, hipótese)")
    parser.add_argument("--recuperacao-expansor", type=_unit_fraction, default=1.0,
                        help="fração do trabalho do expansor aproveitada no eixo [0–1]; padrão 1: transmissão ideal")
    parser.add_argument("--grupo", choices=("todos", "economizador", "flash", "ejetor", "mistas", "expansor", "turbina"),
                        default="todos", help="grupo de configurações na análise comparacao")
    parser.add_argument("--replotar", action="store_true",
                        help="refaz a comparação com CSVs compatíveis, sem recalcular ciclos")
    parser.add_argument("--comparar-subcooler", action="store_true",
                        help="compara componentes com/sem subcooler e a cascata sem componentes adicionais")
    parser.add_argument("--comparar-fonte", action="store_true",
                        help="também compara COP versus entrada da fonte, com --temperatura-baixa fixa")
    return parser


def selected_case(args):
    explicit_stages = args.baixa is not None or args.alta is not None
    if explicit_stages and (args.componente != "simples" or args.estagio != "ambos"):
        raise ValueError("Use --baixa/--alta OU --componente/--estagio, sem misturar as opções.")
    if args.ciclo == "alta":
        if explicit_stages or args.componente != "simples":
            raise ValueError("O ciclo de alta isolado está disponível, por enquanto, sem injeção.")
        if args.analise in ("curva", "mapa", "comparacao"):
            raise ValueError("Curva, mapa e comparação de temperaturas estão definidos para a cascata.")
    if explicit_stages:
        low = TECHNOLOGY[args.baixa or "simples"]
        high = TECHNOLOGY[args.alta or "simples"]
    else:
        tech = TECHNOLOGY[args.componente]
        low = tech if args.estagio in ("baixa", "ambos") else "simple"
        high = tech if args.estagio in ("alta", "ambos") else "simple"
    name = next((n for n, l, h in ARCHITECTURES if (l, h) == (low, high)), None)
    if name is None:
        raise ValueError("Combinação de componentes não cadastrada. O estudo inicial do expansor "
                         "inclui baixa, alta ou ambos com o outro ciclo convencional, sem híbridos adicionais.")
    p = ComponentParams(
        Q_target=args.carga * 1000,
        T_source_in=args.fonte,
        T_cd_l_step=args.tolerancia,
        low_technology=low,
        high_technology=high,
        use_subcooler=args.subcooler,
        optimize_injection=any(t in ("flash_tank", "economizer") for t in (low, high)),
        **_expander_options(args),
    )
    if args.ciclo == "alta":
        name = "High-stage cycle"
    return name, p


def case_folder(name, args):
    slug = name.lower().replace(" / ", "__").replace(" ", "_")
    cycle = "cascata" if args.ciclo == "cascata" else "estagio_alto"
    return ROOT / "results" / cycle / slug / args.analise


def run_point(label, p, args, output):
    if args.ciclo == "cascata":
        cycle, _ = model.otimizar_cascata(p)
    else:
        cycle = model.ciclo_alta(p)
    row = record(label, p, cycle) if args.ciclo == "cascata" else {
        "configuration": label, "status": "valid", "COP": cycle["COP"],
        "Q_useful_kW": cycle["Q_total"] / 1000, "W_shaft_kW": cycle["W_total"] / 1000,
        "high_evaporation_C": cycle["high"]["T_ev"],
        "high_condensation_C": cycle["high"]["T_cd"],
    }
    if args.ciclo == "cascata" and hasattr(args, "_optima_cache"):
        args._optima_cache[label] = row
    output.mkdir(parents=True, exist_ok=True)
    save_rows([row], output / "result.csv")
    (output / "conditions.json").write_text(
        json.dumps({"cycle": args.ciclo, "analysis": args.analise,
                    "case": label, "parameters": asdict(p)}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(f"Configuração: {label}")
    if args.ciclo == "cascata":
        print(f"T ótima de condensação da baixa: {cycle['T_cd_l']:.2f} °C")
        print(f"T de evaporação da alta: {cycle['T_ev_h']:.2f} °C")
        for stage in ("low", "high"):
            result = cycle[stage]
            if result.get("P_int") is not None:
                print(f"Pressão intermediária ({stage}): {result['P_int']:.3f} bar")
            if "P_separator" in result:
                print(f"Ejetor ({stage}): evaporação {result['P_ev']:.3f} bar; "
                      f"sucção {result['P_suction']:.3f} bar; "
                      f"razão de arraste {result['ejector_entrainment_ratio']:.4f}; "
                      f"IHX {result['Q_ihx']/1000:.2f} kW (interno)")
            if "expander_isentropic_efficiency" in result:
                print(f"Expansor ({stage}): saída {result['P_ev']:.3f} bar; "
                      f"potência gerada {result['W_expander']/1000:.3f} kW; "
                      f"aproveitada {result['W_recovered']/1000:.3f} kW")
    print(f"COP: {cycle['COP']:.4f}")
    if args.ciclo == "cascata" and "expander" in (p.low_technology, p.high_technology):
        print(f"Potência bruta dos compressores: {row['W_compressor_shaft_kW']:.2f} kW")
        print(f"Potência líquida de entrada no eixo: {row['W_net_shaft_kW']:.2f} kW")
        print(f"Hipóteses: eficiência isentrópica {p.expander_isentropic_efficiency:g}; "
              f"fração aproveitada no eixo {p.expander_recovery_efficiency:g}")
    else:
        print(f"Potência dos compressores: {cycle['W_total'] / 1000:.2f} kW")
    print(f"Resultados: {output}")


def run_curve(label, p, args, output):
    temperatures = np.linspace(p.T_cd_l_min, model.T_cd_l_max(p), args.pontos)
    rows = [evaluate(label, p, t) for t in temperatures]
    if hasattr(args, "_curve_cache"):
        args._curve_cache[label] = rows
    cycle, _ = model.otimizar_cascata(p)
    optimum = record(label, p, cycle)
    save_rows(rows, output / "curve.csv")
    save_rows([optimum], output / "optimum.csv")
    plot_curves([(label, rows)], "high_evaporation_C", "COP",
                "High-stage evaporation temperature [°C]", "COP [-]",
                "Cascade COP", output / "cop_vs_high_stage_evaporation", p)
    print(f"Ponto ótimo: {cycle['T_cd_l']:.2f} °C | COP {cycle['COP']:.4f}")
    print(f"Resultados: {output}")


def run_map(label, p, args, output):
    sources = np.linspace(5.0, 40.0, args.pontos)
    high_evaporations = np.linspace(
        p.T_cd_l_min - p.DT_pinch_cascade,
        model.T_cd_l_max(p) - p.DT_pinch_cascade,
        args.pontos,
    )
    rows = []
    values = np.full((len(high_evaporations), len(sources)), np.nan)
    for i, tev_high in enumerate(high_evaporations):
        tcond = tev_high + p.DT_pinch_cascade
        for j, tsource in enumerate(sources):
            case = replace(p, T_source_in=float(tsource))
            row = evaluate(label, case, float(tcond))
            rows.append(row)
            if row["status"] == "valid":
                values[i, j] = row["COP"]
    save_rows(rows, output / "map.csv")
    good = [r for r in rows if r["status"] == "valid"]
    if not good:
        raise ValueError("Nenhum ponto viável neste mapa.")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(190 * MM, 125 * MM))
    finite = values[np.isfinite(values)]
    minimum, maximum = float(finite.min()), float(finite.max())
    if maximum - minimum < 1e-8:
        minimum, maximum = minimum - 0.01, maximum + 0.01
    fill_levels = np.linspace(minimum, maximum, 25)
    image, _ = heatmap(
        ax, sources, high_evaporations, np.ma.masked_invalid(values),
        cbar_label="Overall COP [-]", levels=fill_levels,
    )
    if finite.max() - finite.min() > 1e-8:
        contour_levels = np.linspace(float(finite.min()), float(finite.max()), 7)[1:-1]
        contours = ax.contour(sources, high_evaporations,
                              np.ma.masked_invalid(values),
                              levels=contour_levels, colors="black", linewidths=0.65)
        ax.clabel(contours, inline=True, fontsize=8, fmt="%.2f")
    ax.set(xlabel="Heat-source inlet temperature [°C]",
           ylabel="High-stage evaporation temperature [°C]",
           title=(f"Cascade COP — {label}\n"
                  f"{p.Q_target / 1000:g} kW | saturated water at "
                  f"{p.T_sat_w_cond:g} °C | cascade pinch = "
                  f"{p.DT_pinch_cascade:g} K | "
                  f"{'with' if p.use_subcooler else 'without'} subcooler"))
    ax.set_xlim(float(sources.min()), float(sources.max()))
    ax.set_ylim(float(high_evaporations.min()), float(high_evaporations.max()))
    save_figure(fig, output / "cop_map")
    plt.close(fig)
    print(f"Mapa salvo em: {output}")


def run_source(label, p, args, output):
    temps = np.linspace(5.0, 40.0, args.pontos)
    rows = [evaluate(label, replace(p, T_source_in=float(t)), args.temperatura_baixa)
            for t in temps]
    save_rows(rows, output / "source_sweep.csv")
    plot_curves([(label, rows)], "source_inlet_C", "COP",
                "Heat-source inlet temperature [°C]", "COP [-]",
                f"Cascade COP — low-stage condensation at {args.temperatura_baixa:g} °C",
                output / "cop_vs_heat_source_temperature", p)
    print(f"Curva salva em: {output}")


def run_comparison(args, output):
    if args.comparar_subcooler:
        from hthp.component_comparison import run_component_comparison
        return run_component_comparison(args, Path(output) / "adicao_componentes")
    output = Path(output)
    p = ComponentParams(Q_target=args.carga * 1000, T_source_in=args.fonte,
                        T_cd_l_step=args.tolerancia, use_subcooler=args.subcooler,
                        **_expander_options(args))
    views = comparison_views(args.grupo)
    cases = view_cases(views)
    signature = solver_signature()
    metadata = comparison_metadata(p, args.pontos, signature, cases)
    if args.replotar:
        temperatures = np.linspace(p.T_cd_l_min, model.T_cd_l_max(p), args.pontos)
        errors = []
        for source in dict.fromkeys((output / "todas_combinacoes", output / views[0].folder)):
            try:
                summaries, groups = load_comparison_data(source, metadata, cases, temperatures)
                print(f"Reutilizando resultados compatíveis de: {source}", flush=True)
                break
            except (OSError, ValueError, KeyError) as error:
                errors.append(str(error))
        else:
            raise ValueError("Não há resultados completos e compatíveis para replotar. "
                             "Execute primeiro sem --replotar. " + errors[-1])
    else:
        summaries = _calculate_comparison_optima(args, p, cases)
        groups = _calculate_architecture_curves(args, p, cases)
    summaries.sort(key=lambda row: (row["status"] != "valid", -float(row.get("COP") or 0)))
    for view in views:
        labels = {case[0] for case in view.cases}
        subset = [(label, rows) for label, rows in groups if label in labels]
        summary = [row for row in summaries if row["configuration"] in labels]
        destination = output / view.folder
        destination.mkdir(parents=True, exist_ok=True)
        conditions = comparison_metadata(p, args.pontos, signature, view.cases)
        conditions.update(reference=view.reference, gain_comparison="same low-stage condensation temperature")
        (destination / "conditions.json").write_text(
            json.dumps(conditions, indent=2, ensure_ascii=False), encoding="utf-8")
        save_rows(summary, destination / "optima.csv")
        if "Conventional cascade" in labels:
            save_optimum_report(summary, p, destination,
                                render=view.folder in ("todas_combinacoes", "por_componente/expansor"))
        save_rows([row for _, rows in subset for row in rows],
                  destination / "architecture_temperature_sweeps.csv")
        if view.all_metrics:
            _plot_architecture_curves(args, p, destination, groups=subset, cop_title=view.title)
        else:
            plot_curves(subset, "low_condensation_C", "COP",
                        "Low-stage condensation temperature [°C]", "Overall COP [-]",
                        view.title, destination / "cop_vs_low_stage_condensation", p)
        gains = relative_cop_groups(subset, view.reference)
        save_rows([row for _, rows in gains for row in rows], destination / "cop_gains.csv")
        plot_curves(gains, "low_condensation_C", "COP_gain_percent",
                    "Low-stage condensation temperature [°C]", "COP change [%]",
                    view.title.replace("Cascade COP", "Cascade COP change"),
                    destination / "cop_gain_vs_low_stage_condensation", p,
                    legend_title=f"Reference: {view.reference}\nAt the same intermediate temperature")
        print(f"Gráficos e tabela: {destination}", flush=True)
    if args.grupo == "todos":
        # Preserve the previous ten-case plots and their familiar filenames.
        labels = {case[0] for case in BASE_ARCHITECTURES}
        legacy = [(label, rows) for label, rows in groups if label in labels]
        save_rows([row for row in summaries if row["configuration"] in labels], output / "optima.csv")
        (output / "conditions.json").write_text(
            json.dumps(comparison_metadata(p, args.pontos, signature, BASE_ARCHITECTURES),
                       indent=2, ensure_ascii=False), encoding="utf-8")
        _plot_architecture_curves(args, p, output / "temperature_curves", groups=legacy)
    valid = [row for row in summaries if row["status"] == "valid"]
    if not valid:
        raise ValueError("Nenhuma configuração com ponto ótimo viável neste grupo.")
    best = valid[0]
    if args.comparar_fonte:
        from hthp.source_comparison import run_source_comparison
        run_source_comparison(args, p, views, output)
    print(f"Maior COP encontrado: {best['configuration']} | {float(best['COP']):.4f} | "
          f"condensação da baixa: {float(best['low_condensation_C']):.2f} °C")
    print(f"Resumo: {output / views[0].folder}")


def _calculate_comparison_optima(args, p, cases):
    summaries = []
    for index, (label, low, high) in enumerate(cases, 1):
        print(f"Ótimo {index}/{len(cases)}: {label}", flush=True)
        case = replace(p, low_technology=low, high_technology=high,
                       optimize_injection=any(t in ("flash_tank", "economizer") for t in (low, high)))
        cached = getattr(args, "_optima_cache", {}).get(label)
        if cached is None:
            try:
                cycle, _ = model.otimizar_cascata(case)
                cached = record(label, case, cycle)
            except ValueError as error:
                cached = dict(configuration=label, status="invalid", reason=str(error))
        summaries.append(cached)
        if cached["status"] == "valid":
            print(f"  COP ótimo {float(cached['COP']):.4f}", flush=True)
        else:
            print(f"  Sem ótimo viável: {cached['reason']}", flush=True)
    return summaries


def _calculate_architecture_curves(args, p, cases):
    temperatures = np.linspace(p.T_cd_l_min, model.T_cd_l_max(p), args.pontos)
    cache = getattr(args, "_curve_cache", {})
    groups = []
    for index, (label, low, high) in enumerate(cases, 1):
        print(f"Curva {index}/{len(cases)}: {label}", flush=True)
        if label in cache:
            rows = cache[label]
        else:
            case = replace(p, low_technology=low, high_technology=high,
                           optimize_injection=any(t in ("flash_tank", "economizer") for t in (low, high)))
            rows = [evaluate(label, case, float(t)) for t in temperatures]
        groups.append((label, rows))
    return groups


def _plot_architecture_curves(args, p, output, groups=None,
                              cop_title="Cascade COP — architecture comparison"):
    """Make like-for-like curves for every cascade architecture.

    The swept variable and x axis are the low-stage condensing temperature,
    matching the comparison figure requested for the cascade analyses.
    """
    output.mkdir(parents=True, exist_ok=True)
    if groups is None:
        groups = _calculate_architecture_curves(args, p, BASE_ARCHITECTURES)
    combined_rows = [row for _, rows in groups for row in rows]
    save_rows(combined_rows, output / "architecture_temperature_sweeps.csv")
    x_label = "Low-stage condensation temperature [°C]"
    plot_curves(groups, "low_condensation_C", "COP", x_label, "Overall COP [-]",
                cop_title,
                output / "cop_vs_low_stage_condensation", p)
    has_expander = any("expander" in label.lower() for label, _ in groups)
    plot_curves(groups, "low_condensation_C", "W_shaft_kW", x_label,
                "Net shaft input [kW]" if has_expander else "Compressor shaft power [kW]",
                "Cascade net power — architecture comparison" if has_expander
                else "Cascade compressor power — architecture comparison",
                output / "power_vs_low_stage_condensation", p)
    if has_expander:
        for key, ylabel, title, filename in (
            ("W_compressor_shaft_kW", "Gross compressor shaft power [kW]",
             "Cascade gross compressor power", "gross_compressor_power_vs_low_stage_condensation"),
            ("W_expander_shaft_kW", "Expander shaft output [kW]",
             "Cascade expansion work output", "expander_output_vs_low_stage_condensation"),
            ("W_recovered_kW", "Useful recovered shaft power [kW]",
             "Cascade useful expansion work recovery", "recovered_power_vs_low_stage_condensation"),
        ):
            plot_curves(groups, "low_condensation_C", key, x_label, ylabel,
                        title, output / filename, p)
    plot_curves(groups, "low_condensation_C", "low_discharge_C", x_label,
                "Low-stage discharge temperature [°C]",
                "Low-stage discharge temperature — architecture comparison",
                output / "low_stage_discharge_vs_low_stage_condensation", p)
    plot_curves(groups, "low_condensation_C", "high_discharge_C", x_label,
                "High-stage discharge temperature [°C]",
                "High-stage discharge temperature — architecture comparison",
                output / "high_stage_discharge_vs_low_stage_condensation", p)
    plot_curves(groups, "low_condensation_C", "low_minimum_efficiency", x_label,
                "Minimum compressor isentropic efficiency [-]",
                "Low-stage compressor efficiency — architecture comparison",
                output / "low_stage_efficiency_vs_low_stage_condensation", p)
    plot_curves(groups, "low_condensation_C", "high_minimum_efficiency", x_label,
                "Minimum compressor isentropic efficiency [-]",
                "High-stage compressor efficiency — architecture comparison",
                output / "high_stage_efficiency_vs_low_stage_condensation", p)


def run_selected_analysis(label, p, args):
    output = case_folder(label, args)
    output.mkdir(parents=True, exist_ok=True)
    (output / "conditions.json").write_text(
        json.dumps({"cycle": args.ciclo, "analysis": args.analise,
                    "case": label, "parameters": asdict(p)}, indent=2, ensure_ascii=False),
        encoding="utf-8")

    if args.analise == "ponto":
        run_point(label, p, args, output)
    elif args.analise == "ph":
        if args.ciclo != "cascata":
            raise ValueError("O diagrama P-h do ciclo isolado de alta não está configurado nesta análise.")
        cycle, _ = model.otimizar_cascata(p)
        save_rows([record(label, p, cycle)], output / "optimal_point.csv")
        ph_analysis(p, [(label, p)], output, cycles=[cycle])
        print(f"P-h no ponto ótimo: Tcond,baixa = {cycle['T_cd_l']:.2f} °C; "
              f"COP = {cycle['COP']:.4f}")
        print(f"Diagramas e estados salvos em: {output}")
    elif args.analise == "curva":
        run_curve(label, p, args, output)
    elif args.analise == "mapa":
        run_map(label, p, args, output)
    elif args.analise == "fonte":
        run_source(label, p, args, output)
    else:
        raise ValueError(f"Análise desconhecida: {args.analise}")


def run_all_architectures(args):
    args._optima_cache = {}
    args._curve_cache = {}
    base = ComponentParams(
        Q_target=args.carga * 1000,
        T_source_in=args.fonte,
        T_cd_l_step=args.tolerancia,
        use_subcooler=args.subcooler,
        **_expander_options(args),
    )
    analyses = ("ponto", "curva", "ph", "mapa", "fonte")
    for label, low, high in ARCHITECTURES:
        print(f"\n=== {label} ===", flush=True)
        p = replace(base, low_technology=low, high_technology=high,
                    optimize_injection=any(t in ("flash_tank", "economizer") for t in (low, high)))
        for analysis in analyses:
            args.analise = analysis
            run_selected_analysis(label, p, args)

    args.analise = "comparacao"
    run_comparison(args, ROOT / "results" / "cascata" / "comparacao")
    # Add both subcooler versions, but preserve the user's original option.
    from hthp.component_comparison import run_component_comparison
    run_component_comparison(args, ROOT / "results" / "cascata" / "comparacao" / "adicao_componentes")
    args.analise = "all"


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "all":
        args.analise = "all"
    if args.carga <= 0 or args.pontos < 3 or args.tolerancia <= 0:
        parser.error("carga e tolerância devem ser positivas; use pelo menos 3 pontos.")
    if (args.grupo != "todos" or args.replotar or args.comparar_subcooler or args.comparar_fonte) and args.analise != "comparacao":
        parser.error("--grupo, --replotar, --comparar-subcooler e --comparar-fonte são opções da análise comparacao.")
    if args.comparar_fonte and args.comparar_subcooler:
        parser.error("Para variar a fonte, escolha --subcooler ou --sem-subcooler em execuções separadas.")
    if args.comparar_subcooler and not args.subcooler:
        parser.error("--comparar-subcooler já inclui as duas versões; retire --sem-subcooler.")
    if args.analise == "comparacao" and args.ciclo != "cascata":
        parser.error("A comparação está definida para o ciclo cascata.")
    if args.analise == "all" and (args.baixa is not None or args.alta is not None):
        parser.error("'all' roda todas as combinações; retire --baixa e --alta.")
    try:
        if args.analise == "all":
            if args.ciclo != "cascata":
                raise ValueError("'all' está disponível somente para o ciclo cascata.")
            run_all_architectures(args)
            return

        label, p = selected_case(args)
        if args.analise == "comparacao":
            run_comparison(args, ROOT / "results" / "cascata" / "comparacao")
            return
        run_selected_analysis(label, p, args)
    except (ValueError, RuntimeError) as error:
        parser.exit(2, f"Erro: {error}\n")


if __name__ == "__main__":
    main()
