"""Result tables and plots for a chosen heat-pump case."""

import csv
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from hthp.plots.style import COLORS, DASHES, add_minor_grid, save_figure

from hthp import model


def save_rows(rows, path):
    if not rows:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _compressors(stage, p, suffix):
    if "compressors" in stage:
        return stage["compressors"]
    rp = stage["RP"]
    a, b, c = (getattr(p, key + suffix) for key in ("a_is_", "b_is_", "c_is_"))
    raw = a + b * rp + c * rp**2
    return [dict(RP=rp, eta_is=stage["eta_is"], eta_raw=raw,
                 T_discharge=stage["T2"], limited=not p.eta_is_min <= raw <= p.eta_is_max)]


def record(label, p, cycle):
    from hthp.configurations import has_injection
    low, high = cycle["low"], cycle["high"]
    compressor_power = sum(s.get("W_compressor", s["W"]) for s in (low, high))
    expander_power = sum(s.get("W_expander", 0.0) for s in (low, high))
    recovered_power = sum(s.get("W_recovered", 0.0) for s in (low, high))
    recovery_loss = sum(s.get("W_recovery_loss", 0.0) for s in (low, high))
    row = dict(
        configuration=label, status="valid", with_high_stage_subcooler=p.use_subcooler,
        low_fluid=p.F_l, high_fluid=p.F_h, Q_useful_kW=cycle["Q_total"] / 1000,
        COP=cycle["COP"], W_shaft_kW=cycle["W_total"] / 1000,
        W_net_shaft_kW=cycle["W_total"] / 1000,
        W_compressor_shaft_kW=compressor_power / 1000,
        W_expander_shaft_kW=expander_power / 1000,
        W_recovered_kW=recovered_power / 1000,
        W_recovery_loss_kW=recovery_loss / 1000,
        source_inlet_C=p.T_source_in, source_outlet_C=cycle["T_source_out"],
        water_inlet_C=cycle["T_w_cond_in"], water_outlet_C=cycle["T_w_cond_out"],
        water_outlet_quality=cycle["titulo_w_cond_out"], water_pressure_bar=p.P_w_cond,
        water_outlet_phase=cycle["fase_w_cond_out"], low_condensation_C=cycle["T_cd_l"],
        high_evaporation_C=cycle["T_ev_h"], low_evaporation_C=cycle["T_ev_l"],
        high_condensation_C=cycle["T_cd_h"], subcooler_heat_kW=high["Q_sc"] / 1000,
        # Unused shaft output leaves the useful system boundary; it cannot be
        # silently returned to the source, condenser or recovered power.
        energy_residual_W=cycle["Q_total"] + recovery_loss - cycle["W_total"] - low["Q_ev"],
        cascade_residual_W=cycle["residual_cascade"], condenser_heat_kW=high["Q_cond"] / 1000,
        source_heat_kW=low["Q_ev"] / 1000, source_mass_flow_kg_s=cycle["m_dot_source"],
        water_mass_flow_kg_s=cycle["m_dot_w_cond"], pinch_condenser_K=p.DT_pinch_cond,
        pinch_cascade_K=p.DT_pinch_cascade, pinch_evaporator_K=p.DT_pinch_evap,
        pinch_subcooler_K=p.DT_pinch_sc, condenser_subcooling_low_K=p.SUB_l,
        condenser_subcooling_high_K=p.SUB_h,
        intermediate_pressures_optimized=p.optimize_injection and any(
            has_injection(technology)
            for technology in (p.low_technology, p.high_technology)),
    )
    for prefix, stage, suffix in (("low", low, "l"), ("high", high, "h")):
        row[prefix + "_compressor_shaft_power_kW"] = stage.get("W_compressor", stage["W"]) / 1000
        row[prefix + "_expander_shaft_power_kW"] = stage.get("W_expander", 0.0) / 1000
        row[prefix + "_recovered_power_kW"] = stage.get("W_recovered", 0.0) / 1000
        row[prefix + "_unrecovered_power_kW"] = stage.get("W_recovery_loss", 0.0) / 1000
        if "expander_isentropic_efficiency" in stage:
            for field in ("expander_isentropic_efficiency", "expander_recovery_efficiency",
                          "expander_inlet_quality", "expander_outlet_quality",
                          "expander_inlet_entropy_kJ_kgK", "expander_outlet_entropy_kJ_kgK"):
                row[prefix + "_" + field] = stage.get(field, "")
        row[prefix + "_injection_pressure_bar"] = stage.get("P_int", "")
        row[prefix + "_injection_fraction"] = stage.get("injection_fraction", 0.0)
        row[prefix + "_refrigerant_mass_flow_kg_s"] = stage["m_dot"]
        row[prefix + "_evaporator_mass_flow_kg_s"] = stage.get("m_dot_evap", stage["m_dot"])
        row[prefix + "_injected_mass_flow_kg_s"] = stage["m_dot"] * stage.get("injection_fraction", 0.0)
        row[prefix + "_discharge_C"] = stage["T2"]
        row[prefix + "_evaporator_pressure_bar"] = stage["P_ev"]
        row[prefix + "_suction_pressure_bar"] = stage.get("P_suction", stage["P_ev"])
        if "P_separator" in stage:
            for field in ("P_separator", "ejector_entrainment_ratio",
                          "ejector_pressure_lift_ratio", "separator_vapor_quality",
                          "ejector_closure_residual", "separator_mass_residual",
                          "Q_ihx", "ihx_balance_residual", "ihx_minimum_approach_K",
                          "compressor_superheat_K", "evaporator_superheat_K"):
                row[prefix + "_" + field] = stage[field]
        compressors = _compressors(stage, p, suffix)
        row[prefix + "_maximum_discharge_C"] = max(c["T_discharge"] for c in compressors)
        row[prefix + "_minimum_efficiency"] = min(c["eta_is"] for c in compressors)
        row[prefix + "_efficiency_limited"] = any(c["limited"] for c in compressors)
        for index, compressor in enumerate(compressors, 1):
            for key in ("RP", "eta_is", "eta_raw", "T_discharge"):
                row[f"{prefix}_compression_{index}_{key}"] = compressor[key]
    return row


def plot_curves(groups, xkey, ykey, xlabel, ylabel, title, path, p, legend_title=None,
                subcooler_comparison=False):
    from hthp.comparisons import compact_label
    from hthp.configurations import ARCHITECTURES

    style_indices = {case[0]: index for index, case in enumerate(ARCHITECTURES)}
    if len(groups) >= 20:
        # Reserve physical space for large legends: 20-label paired families,
        # the 25-architecture comparison and the complete 50-label campaign.
        legend_rows = (len(groups) + 1) // 2
        height_mm = 130 + 4 * legend_rows
        bottom = (16 + 4 * legend_rows) / height_mm
        fig, ax = plt.subplots(figsize=(190/25.4, height_mm/25.4), layout="none")
        fig.subplots_adjust(left=0.13, right=0.98, top=0.89, bottom=bottom)
    else:
        fig, ax = plt.subplots()
    def value(row):
        if row["status"] != "valid":
            return np.nan
        try:
            return float(row.get(ykey, np.nan))
        except (TypeError, ValueError):
            return np.nan

    for index, (label, rows) in enumerate(groups):
        base_label = rows[0].get("base_configuration", label) if rows else label
        index = style_indices.get(base_label, index)
        # Preserve every legacy style; additional architectures get a new
        # color/dash pairing rather than repeating case zero at index 25.
        generation = index // len(COLORS)
        color_index = (index + 7 * generation) % len(COLORS)
        line_style = DASHES[(index + 3 * generation) % len(DASHES)]
        display_label = compact_label(label)
        if subcooler_comparison and rows:
            with_subcooler = rows[0]["with_high_stage_subcooler"]
            line_style = "-" if with_subcooler else "--"
            display_label = compact_label(base_label) + (
                " + subcooler" if with_subcooler else " (no subcooler)")
        points = [row for row in rows if xkey in row]
        if points:
            ax.plot([row[xkey] for row in points],
                    [value(row) for row in points], color=COLORS[color_index],
                    linestyle=line_style, marker="none", label=display_label)
    if p.MODO_AGUA_COND == "SATURADO":
        water_condition = f"saturated water at {p.T_sat_w_cond:g} °C"
    else:
        water_condition = (
            f"water {p.T_w_cond_in:g} °C at {p.P_w_cond_liq:g} bar"
        )
    subcooler_condition = "high-stage subcooler" if p.use_subcooler else "no subcooler"
    if subcooler_comparison:
        subcooler_condition = "with / without high-stage subcooler"
    conditions = f"{p.Q_target / 1000:g} kW | {water_condition} | {subcooler_condition}"
    if any("expander" in label.lower() for label, _ in groups):
        conditions += (f"\nExpander: $\\eta_{{is}}$ = {p.expander_isentropic_efficiency:g} | "
                       f"useful shaft fraction = {p.expander_recovery_efficiency:g}")
    ax.set(title=f"{title}\n{conditions}", xlabel=xlabel, ylabel=ylabel)
    add_minor_grid(ax)
    if len(groups) > 7 or legend_title:
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.23),
                  ncols=2, fontsize=7 if len(groups) > 10 else 8,
                  title=legend_title, title_fontsize=8)
    else:
        ax.legend(loc="best", ncols=1 if legend_title else 2, fontsize=8 if legend_title else 9,
                  title=legend_title, title_fontsize=8)
    save_figure(fig, path)
    plt.close(fig)


def evaluate(label, p, temperature):
    try:
        cycle = model.ciclo_cascata(p, float(temperature))
        return record(label, p, cycle)
    except ValueError as error:
        return dict(configuration=label, status="invalid", reason=str(error),
                    low_condensation_C=float(temperature), source_inlet_C=p.T_source_in,
                    with_high_stage_subcooler=p.use_subcooler)


def ph_analysis(p, cases, output_dir, cycles=None):
    """Plot the selected cycle stages using their calculated state points."""
    from hthp.plots.cycles.diagrams import plot_cycles
    from hthp.configurations import technology_components

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    states_rows = []
    precomputed = iter(cycles) if cycles is not None else None
    for label, case in cases:
        print(f"Gerando P-h no ponto ótimo: {label}", flush=True)
        cycle = next(precomputed) if precomputed is not None else model.otimizar_cascata(case)[0]
        plots = []
        for stage, key in (("low", "l"), ("high", "h")):
            data = cycle[stage]
            if "component_states" not in data:
                item = model.montar_ciclo_grafico(data, stage)
                labels = [str(index) for index in range(1, len(item["P_bar"]) + 1)]
                item["fill_indices"] = list(range(len(item["P_bar"])))
            else:
                states = data["component_states"]
                labels = list(states)
                item = dict(fluid=data["fluid"], stage=stage,
                            P_bar=[state.pressure_bar for state in states.values()],
                            H_J_kg=[state.enthalpy_kJ_kg * 1000 for state in states.values()])
                technology = case.low_technology if stage == "low" else case.high_technology
                if technology in ("simple", "expander"):
                    pairs = [(1, 2, "-"), (2, 3, "-"), (3, "3E", "-"), ("3E", 4, "-"), (4, 1, "-")]
                    main_loop = [1, 2, 3, "3E", 4]
                elif technology in ("ejector", "ejector_expander"):
                    pairs = [("suction", "discharge", "-"),
                             ("discharge", "condenser_out", "-"),
                             ("condenser_out", "subcooler_out", "-"),
                             ("subcooler_out", "motive_in", "-"),
                             ("motive_in", "nozzle_out", "-"),
                             ("nozzle_out", "mixing", "--"),
                             ("evaporator_out", "mixing", "--"),
                             ("mixing", "ejector_out", "-"),
                             ("ejector_out", "separator_vapour", "--"),
                             ("ejector_out", "separator_liquid", "--"),
                             ("separator_vapour", "suction", "-"),
                             ("separator_liquid", "evaporator_in", "-"),
                             ("evaporator_in", "evaporator_out", "-")]
                    # Branched ejector processes are not one simple polygon.
                    main_loop = []
                elif technology in ("flash_ejector", "economizer_ejector"):
                    pairs = [("suction", "first_discharge", "-"),
                             ("first_discharge", "mixed", "--"),
                             ("injection_vapour", "mixed", "--"),
                             ("mixed", "discharge", "-"),
                             ("discharge", "condenser_out", "-"),
                             ("condenser_out", "subcooler_out", "-"),
                             ("subcooler_out", "injection_in", "-"),
                             ("main_after_injection_hx", "motive_in", "-"),
                             ("motive_in", "nozzle_out", "-"),
                             ("nozzle_out", "mixing", "--"),
                             ("evaporator_out", "mixing", "--"),
                             ("mixing", "ejector_out", "-"),
                             ("ejector_out", "separator_vapour", "--"),
                             ("ejector_out", "separator_liquid", "--"),
                             ("separator_vapour", "suction", "-"),
                             ("separator_liquid", "evaporator_in", "-"),
                             ("evaporator_in", "evaporator_out", "-")]
                    if technology == "flash_ejector":
                        pairs += [("injection_in", "injection_vapour", "--"),
                                  ("injection_in", "main_after_injection_hx", "--")]
                    else:
                        pairs += [("injection_in", "injection_vapour", "-"),
                                  ("subcooler_out", "main_after_injection_hx", "-")]
                    main_loop = []
                else:
                    pairs = [("1", "2", "-"), ("2", "3", "--"), ("3", "4", "-"),
                             ("4", "5", "-"), ("5", "5E", "-")]
                    if "flash_tank" in technology_components(technology):
                        pairs += [("5E", "6", "-"), ("6", "6L", "--"), ("6", "6V", "--"),
                                  ("6L", "7", "-"), ("7", "1", "-"), ("6V", "3", "--")]
                        main_loop = ["1", "2", "3", "4", "5", "6L", "7"]
                    else:
                        pairs += [("5E", "6", "-"), ("6", "7", "-"), ("7", "1", "-"),
                                  ("5E", "8", "-"), ("8", "9", "-"), ("9", "3", "--")]
                        main_loop = ["1", "2", "3", "4", "5", "5E", "6", "7"]
                item["connections"] = [(labels.index(a), labels.index(b), style)
                                       for a, b, style in pairs]
                item["fill_indices"] = [labels.index(name if name in labels else str(name))
                                        for name in main_loop]
            numbers = []
            state_numbers = {}
            next_state_number = 1
            for index, (name, pressure, enthalpy) in enumerate(
                    zip(labels, item["P_bar"], item["H_J_kg"]), 1):
                state_key = (data["fluid"], round(float(pressure), 8),
                             round(float(enthalpy) / 1000, 6))
                if state_key not in state_numbers:
                    state_numbers[state_key] = next_state_number
                    next_state_number += 1
                point_number = state_numbers[state_key]
                numbers.append(str(point_number))
                states_rows.append(dict(configuration=label, stage=stage, number=point_number,
                                        solver_state=str(name), fluid=data["fluid"],
                                        pressure_bar=pressure, enthalpy_kJ_kg=enthalpy / 1000,
                                        low_condensation_C=cycle["T_cd_l"], COP=cycle["COP"]))
            item["point_labels"] = numbers
            plots.append(item)
        fig, ax = plot_cycles(plots, "Ph")
        fig.suptitle(f"Cascade P–h diagram — {label}", fontsize=13)
        ax.set_title(
            f"COP-optimal point | Low-stage condensation: {cycle['T_cd_l']:.1f} °C | "
            f"High-stage evaporation: {cycle['T_ev_h']:.1f} °C | COP: {cycle['COP']:.3f}",
            fontsize=9,
        )
        save_figure(fig, output_dir / "cascade")
        plt.close(fig)
    save_rows(states_rows, output_dir / "states.csv")
