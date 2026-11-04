"""Compact reports of already optimized cases; never run a thermodynamic solver."""

import math
import json
from dataclasses import asdict, replace
from pathlib import Path

from hthp.analyses import save_rows
from hthp.configurations import ARCHITECTURES


STAGE_NAMES = {
    "simple": "Convencional", "flash_tank": "Flash tank",
    "economizer": "Economizador", "ejector": "Ejetor + IHX",
    "expander": "Expansor",
}


def save_combined_optima_report(summaries, p, output, signature):
    """Keep the full 38-case table separate from any temperature-sweep cache."""
    expected = {(label, enabled) for label, _, _ in ARCHITECTURES for enabled in (False, True)}
    summary = build_optimum_summary(summaries, p)
    actual = {(row["base_configuration"], row["with_high_stage_subcooler"]) for row in summary}
    if actual != expected:
        raise ValueError("A tabela completa requer as 19 arquiteturas com e sem subcooler (38 casos).")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    ordered = sorted(summaries, key=lambda row: (row["status"] != "valid", -float(row.get("COP") or 0)))
    save_rows(ordered, output / "optima.csv")
    metadata = dict(analysis="pontos_otimos", solver_signature=signature,
                    parameters_by_subcooler={str(enabled): asdict(replace(p, use_subcooler=enabled))
                                             for enabled in (False, True)},
                    cases=[dict(configuration=label, low=low, high=high) for label, low, high in ARCHITECTURES],
                    case_count=len(summary), optimization="scipy.optimize.minimize_scalar (bounded)",
                    gain_comparison="each case at its own optimum; conventional with matching subcooler setting")
    (output / "conditions.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return save_optimum_report(ordered, p, output, render=True)


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _flag(value, default=False):
    if value is None or value == "":
        return default
    if isinstance(value, str):
        if value.lower() in ("true", "1", "yes", "sim"):
            return True
        if value.lower() in ("false", "0", "no", "não", "nao"):
            return False
        raise ValueError(f"Indicador de subcooler inválido: {value}")
    return bool(value)


def build_optimum_summary(summaries, p, reference="Conventional cascade"):
    """Compare each case's own optimum with the same-SC conventional optimum.

    Missing metrics remain unavailable. Invalid configurations stay in the
    table, with their reason. Explicit boundary flags are copied, not inferred.
    """
    registry = {label: (low, high) for label, low, high in ARCHITECTURES}
    result = []
    seen = set()
    for raw in summaries:
        label = str(raw.get("configuration", "Configuração não identificada"))
        base = raw.get("base_configuration", label)
        enabled = _flag(raw.get("with_high_stage_subcooler"), p.use_subcooler)
        identity = (base, enabled)
        if identity in seen:
            raise ValueError(f"Configuração duplicada na tabela de ótimos: {label}")
        seen.add(identity)
        low, high = registry.get(base, ("", ""))
        cop = _number(raw.get("COP"))
        valid = raw.get("status") == "valid" and cop is not None and cop > 0
        reason = str(raw.get("reason") or "")
        if raw.get("status") == "valid" and not valid:
            reason = reason or "COP ótimo ausente, não finito ou não positivo."
        item = dict(
            configuration=label, base_configuration=base,
            low_component=low, high_component=high,
            low_stage=STAGE_NAMES.get(low, "Não identificado"),
            high_stage=STAGE_NAMES.get(high, "Não identificado"),
            with_high_stage_subcooler=enabled,
            status="valid" if valid else "invalid", reason=reason,
            COP_max=cop if valid else None,
            low_condensation_optimum_C=_number(raw.get("low_condensation_C")),
            high_evaporation_optimum_C=_number(raw.get("high_evaporation_C")),
            W_net_shaft_kW=_number(raw.get("W_net_shaft_kW", raw.get("W_shaft_kW"))),
            W_recovered_kW=_number(raw.get("W_recovered_kW")),
            COP_gain_at_own_optimum_percent=None,
        )
        for key in ("optimization_boundary", "optimum_at_boundary",
                    "low_efficiency_limited", "high_efficiency_limited"):
            if key in raw:
                item[key] = raw[key]
        result.append(item)
    baselines = {
        row["with_high_stage_subcooler"]: row["COP_max"] for row in result
        if row["base_configuration"] == reference and row["status"] == "valid"
    }
    for row in result:
        baseline = baselines.get(row["with_high_stage_subcooler"])
        if row["status"] == "valid" and baseline is not None:
            row["COP_gain_at_own_optimum_percent"] = 100 * (row["COP_max"] / baseline - 1)
    return sorted(result, key=lambda row: (
        row["status"] != "valid", -(row["COP_max"] or 0), row["configuration"]))


def _formatted(value, decimals=2):
    number = _number(value)
    return "—" if number is None else f"{number:.{decimals}f}"


def _latex(text):
    replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%",
                    "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{",
                    "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(replacements.get(char, char) for char in str(text))


def render_optimum_table(rows, p, output):
    """Readable scientific table, split by subcooler setting when both exist."""
    import matplotlib.pyplot as plt
    from hthp.plots.style import COLORS, save_figure

    settings = sorted({row["with_high_stage_subcooler"] for row in rows})
    for enabled in settings:
        subset = [row for row in rows if row["with_high_stage_subcooler"] == enabled]
        fig = plt.figure(figsize=(8.7, max(3.5, 1.8 + 0.25 * len(subset))), layout="none")
        ax = fig.add_axes((0.035, 0.14, 0.93, 0.72))
        ax.axis("off")
        headers = ["Estágio de baixa", "Estágio de alta", r"$COP_{\max}$",
                   "$T_{\\mathrm{cond,l}}^*$\n[°C]", "$T_{\\mathrm{evap,h}}^*$\n[°C]",
                   "$\\dot W_{\\mathrm{liq}}$\n[kW]", "Ganho*\n[%]"]
        cells = [[row["low_stage"], row["high_stage"], _formatted(row["COP_max"], 3),
                  _formatted(row["low_condensation_optimum_C"]),
                  _formatted(row["high_evaporation_optimum_C"]),
                  _formatted(row["W_net_shaft_kW"]),
                  _formatted(row["COP_gain_at_own_optimum_percent"])] for row in subset]
        table = ax.table(cellText=cells, colLabels=headers, cellLoc="right",
                         colWidths=[0.20, 0.20, 0.10, 0.13, 0.13, 0.12, 0.12], bbox=(0, 0, 1, 1))
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        for (i, j), cell in table.get_celld().items():
            cell.set_linewidth(0.35)
            cell.set_edgecolor("0.85")
            if j < 2:
                cell.get_text().set_ha("left")
            if i == 0:
                cell.set_facecolor(COLORS[0])
                cell.set_text_props(color="white", weight="bold")
                cell.set_height(cell.get_height() * 1.45)
            elif subset[i - 1]["base_configuration"] == "Conventional cascade":
                cell.set_facecolor("#EDF1F4")
            else:
                cell.set_facecolor("white" if i % 2 else "#F7F7F7")
        fig.text(0.5, 0.965, "Pontos ótimos por configuração", ha="center", fontsize=14)
        setting = "subcooler somente na alta" if enabled else "sem subcooler externo"
        fig.text(0.5, 0.92, f"{p.Q_target / 1000:g} kW totais | fonte a {p.T_source_in:g} °C | {setting}",
                 ha="center", fontsize=10)
        note = "* Ganho entre ótimos próprios, relativo ao convencional com o mesmo subcooler."
        if any("expander" in (row["low_component"], row["high_component"]) for row in subset):
            note += (f"\nExpansor: ηis = {p.expander_isentropic_efficiency:g}; "
                     f"fração de eixo aproveitada = {p.expander_recovery_efficiency:g} (hipóteses).")
        fig.text(0.035, 0.025, note, fontsize=8, va="bottom")
        suffix = ("_com_subcooler" if enabled else "_sem_subcooler") if len(settings) > 1 else ""
        with plt.rc_context({"figure.constrained_layout.use": False}):
            save_figure(fig, Path(output) / ("optima_summary" + suffix))
        plt.close(fig)


def save_optimum_report(summaries, p, output, reference="Conventional cascade", render=False):
    """Write compact CSV, readable Markdown, and a copy-ready LaTeX tabular.

    The existing detailed ``optima.csv`` is not changed. Return the summary rows.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = build_optimum_summary(summaries, p, reference)
    save_rows(rows, output / "optima_summary.csv")
    mixed_sc = len({row["with_high_stage_subcooler"] for row in rows}) > 1
    headers = ["Estágio de baixa", "Estágio de alta"]
    if mixed_sc:
        headers.append("SC alta")
    headers += ["COP máximo", "Tcond,baixa* [°C]", "Tevap,alta* [°C]",
                "Potência líquida [kW]", "Ganho entre ótimos [%]"]
    notes = [
        f"Carga útil total: {p.Q_target / 1000:g} kW; fonte: {p.T_source_in:g} °C; "
        f"refrigerantes: {p.F_l} (baixa) / {p.F_h} (alta).",
        "Cada linha apresenta o melhor ponto encontrado para a própria configuração. "
        "O asterisco identifica a temperatura nesse ponto; não significa uma temperatura comum a todos os casos.",
        "Ganho = 100 × (COP máximo da configuração / COP máximo convencional − 1), "
        "sempre com o mesmo estado do subcooler. Nos gráficos de ganho, a referência é comparada à mesma temperatura, "
        "o que é uma comparação diferente.",
    ]
    if mixed_sc:
        notes.append("SC alta: subcooler externo somente no estágio de alta; versões com e sem são calculadas separadamente.")
        notes.append("Nos gráficos de adição de componentes, a referência é o convencional sem subcooler; "
                     "nesta tabela o ganho mantém o mesmo estado do subcooler para isolar o efeito da arquitetura.")
    else:
        enabled = rows[0]["with_high_stage_subcooler"] if rows else p.use_subcooler
        notes.append("Subcooler externo somente no estágio de alta." if enabled
                     else "Sem subcooler externo em ambos os estágios.")
    if any("expander" in (row["low_component"], row["high_component"]) for row in rows):
        notes.append(
            f"Expansor: eficiência isentrópica = {p.expander_isentropic_efficiency:g}; "
            f"fração útil da potência de eixo = {p.expander_recovery_efficiency:g}. "
            "São hipóteses exploratórias, não dados validados de fabricante. A potência líquida desconta a potência recuperada.")
    missing_reference = any(row["status"] == "valid" and
                            row["COP_gain_at_own_optimum_percent"] is None for row in rows)
    if missing_reference:
        notes.append("Ganho indisponível quando falta um ótimo convencional válido com o mesmo estado do subcooler.")
    notes.append("— indica valor indisponível. Casos inviáveis permanecem identificados abaixo da tabela.")
    table = []
    for row in rows:
        cells = [row["low_stage"], row["high_stage"]]
        if mixed_sc:
            cells.append("Sim" if row["with_high_stage_subcooler"] else "Não")
        cells += [_formatted(row["COP_max"], 3),
                  _formatted(row["low_condensation_optimum_C"]),
                  _formatted(row["high_evaporation_optimum_C"]),
                  _formatted(row["W_net_shaft_kW"]),
                  _formatted(row["COP_gain_at_own_optimum_percent"])]
        table.append(cells)
    markdown = ["# Pontos ótimos por configuração", "", *[note + "\n" for note in notes],
                "| " + " | ".join(headers) + " |",
                "| " + " | ".join(["---", "---"] + (["---"] if mixed_sc else []) + ["---:"] * 5) + " |"]
    markdown += ["| " + " | ".join(cells) + " |" for cells in table]
    invalid = [row for row in rows if row["status"] != "valid"]
    if invalid:
        markdown += ["", "## Configurações sem ótimo válido", ""]
        markdown += [f"- {row['configuration']}: {row['reason'] or 'motivo não informado'}." for row in invalid]
    (output / "optima_summary.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    tex_headers = ["Estágio de baixa", "Estágio de alta"] + (["SC alta"] if mixed_sc else [])
    tex_headers += [r"$COP_{\max}$", r"\shortstack{$T_{\mathrm{cond,l}}^*$\\{[°C]}}",
                    r"\shortstack{$T_{\mathrm{evap,h}}^*$\\{[°C]}}",
                    r"\shortstack{$\dot W_{\mathrm{liq}}$\\{[kW]}}",
                    r"\shortstack{$\Delta COP_{\mathrm{opt}}$\\{[\%]}}"]
    latex = ["% Requer \\usepackage{booktabs}; bloco tabular, não documento completo."]
    latex += ["% " + note for note in notes]
    latex += [r"{\small\setlength{\tabcolsep}{4pt}\renewcommand{\arraystretch}{1.12}",
              r"\begin{tabular}{ll" + ("c" if mixed_sc else "") + "rrrrr}",
              r"\toprule", " & ".join(tex_headers) + r" \\", r"\midrule"]
    latex += [" & ".join(_latex(cell) if cell != "—" else "--" for cell in cells) + r" \\" for cells in table]
    latex += [r"\bottomrule", r"\end{tabular}", "}"]
    latex += ["% Caso sem ótimo válido: " + row["configuration"] + ": " + (row["reason"] or "motivo não informado")
              for row in invalid]
    (output / "optima_summary.tex").write_text("\n".join(latex) + "\n", encoding="utf-8")
    if render:
        render_optimum_table(rows, p, output)
    return rows
