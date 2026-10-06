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
from hthp.configurations import ARCHITECTURES, ComponentParams
from hthp.plots.style import MM, add_minor_grid, save_figure
from hthp.plots.heatmap import heatmap


TECHNOLOGY = {
    "simples": "simple", "flash": "flash_tank", "economizador": "economizer"
}
LABEL = {"simple": "simple", "flash_tank": "flash_tank", "economizer": "economizer"}


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
                        help="estágio que recebe o flash tank/economizador")
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
    parser.add_argument("--tolerancia", type=float, default=1.0,
                        help="resolução em °C dos candidatos à condensação ótima da baixa")
    parser.add_argument("--temperatura-baixa", type=float, default=45.0,
                        help="condensação do estágio de baixa fixa nas análises de fonte/mapa")
    return parser


def selected_case(args):
    if args.ciclo == "alta":
        if args.componente != "simples":
            raise ValueError("O ciclo de alta isolado está disponível, por enquanto, sem injeção.")
        if args.analise in ("curva", "mapa", "comparacao"):
            raise ValueError("Curva, mapa e comparação de temperaturas estão definidos para a cascata.")
    tech = TECHNOLOGY[args.componente]
    low = tech if args.estagio in ("baixa", "ambos") else "simple"
    high = tech if args.estagio in ("alta", "ambos") else "simple"
    name = next((n for n, l, h in ARCHITECTURES if (l, h) == (low, high)), None)
    if name is None:
        raise ValueError("Combinação de componentes inválida.")
    p = ComponentParams(
        Q_target=args.carga * 1000,
        T_source_in=args.fonte,
        T_cd_l_step=args.tolerancia,
        low_technology=low,
        high_technology=high,
        use_subcooler=args.subcooler,
        optimize_injection=(low != "simple" or high != "simple"),
    )
    if args.ciclo == "alta":
        name = "High-stage cycle"
    return name, p


def case_folder(name, args):
    slug = name.lower().replace(" ", "_")
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
                print(f"Fração mássica de injeção ({stage}): {result['injection_fraction']:.4%}")
                if 'economizer_pinch_K' in result:
                    print(f"Pinch economizador ({stage}): {result['economizer_pinch_K']:.4f} K; UA requerido: {result['economizer_UA_kW_K']:.4f} kW/K")
    print(f"COP: {cycle['COP']:.4f}")
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
    p = ComponentParams(Q_target=args.carga * 1000, T_source_in=args.fonte,
                        T_cd_l_step=args.tolerancia, use_subcooler=args.subcooler)
    summaries = []
    for label, low, high in ARCHITECTURES:
        case = replace(p, low_technology=low, high_technology=high,
                       optimize_injection=(low != "simple" or high != "simple"))
        cached = getattr(args, "_optima_cache", {}).get(label)
        if cached is None:
            cycle, _ = model.otimizar_cascata(case)
            cached = record(label, case, cycle)
        summaries.append(cached)
        print(f"{label}: COP ótimo {cached['COP']:.4f}",flush=True)
    output.mkdir(parents=True, exist_ok=True)
    (output / "conditions.json").write_text(
        json.dumps({"cycle": "cascata", "analysis": "comparacao",
                    "parameters": asdict(p)}, indent=2, ensure_ascii=False), encoding="utf-8")
    summaries.sort(key=lambda row: row["COP"], reverse=True)
    save_rows(summaries, output / "optima.csv")
    _plot_architecture_curves(args, p, output / "temperature_curves")
    best = summaries[0]
    print(f"Maior COP: {best['configuration']} | {best['COP']:.4f} | "
          f"condensação da baixa: {best['low_condensation_C']:.2f} °C")
    print(f"Resumo: {output}")


def _plot_architecture_curves(args, p, output):
    """Make like-for-like curves for every cascade architecture.

    The swept variable and x axis are the low-stage condensing temperature,
    matching the comparison figure requested for the cascade analyses.
    """
    output.mkdir(parents=True, exist_ok=True)
    temperatures = np.linspace(p.T_cd_l_min, model.T_cd_l_max(p), args.pontos)
    groups = []
    combined_rows = []
    cache = getattr(args, "_curve_cache", {})
    for label, low, high in ARCHITECTURES:
        if label in cache:
            rows = cache[label]
            groups.append((label, rows))
            combined_rows.extend(rows)
            continue
        case = replace(p, low_technology=low, high_technology=high,
                       optimize_injection=(low != "simple" or high != "simple"))
        print(f'Calculando curvas: {label} — {args.pontos} temperaturas',flush=True)
        rows = [evaluate(label, case, float(t)) for t in temperatures]
        groups.append((label, rows))
        combined_rows.extend(rows)
    save_rows(combined_rows, output / "architecture_temperature_sweeps.csv")
    x_label = "Low-stage condensation temperature [°C]"
    plot_curves(groups, "low_condensation_C", "COP", x_label, "Overall COP [-]",
                "Cascade COP — flash tank and economizer comparison",
                output / "cop_vs_low_stage_condensation", p)
    plot_curves(groups, "low_condensation_C", "W_shaft_kW", x_label,
                "Compressor shaft power [kW]",
                "Cascade compressor power — architecture comparison",
                output / "power_vs_low_stage_condensation", p)
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
    )
    analyses = ("ponto", "curva", "ph", "mapa", "fonte")
    for label, low, high in ARCHITECTURES:
        print(f"\n=== {label} ===", flush=True)
        p = replace(base, low_technology=low, high_technology=high,
                    optimize_injection=(low != "simple" or high != "simple"))
        for analysis in analyses:
            args.analise = analysis
            run_selected_analysis(label, p, args)

    args.analise = "comparacao"
    run_comparison(args, ROOT / "results" / "cascata" / "comparacao")
    args.analise = "all"


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "all":
        args.analise = "all"
    if args.carga <= 0 or args.pontos < 3 or args.tolerancia <= 0:
        parser.error("carga e tolerância devem ser positivas; use pelo menos 3 pontos.")
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
