"""Result tables and plots for a chosen heat-pump case."""

import csv
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from hthp.plots.style import COLORS, DASHES, MARKERS, add_minor_grid, save_figure

from hthp import model
from hthp.errors import failure_status


def save_rows(rows, path):
    if not rows:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
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
    low, high = cycle["low"], cycle["high"]
    row = dict(
        configuration=label, status="valid", with_high_stage_subcooler=p.use_subcooler,
        low_fluid=p.F_l, high_fluid=p.F_h, Q_useful_kW=cycle["Q_total"] / 1000,
        COP=cycle["COP"], W_shaft_kW=cycle["W_total"] / 1000,
        source_inlet_C=p.T_source_in, source_outlet_C=cycle["T_source_out"],
        water_inlet_C=cycle["T_w_cond_in"], water_outlet_C=cycle["T_w_cond_out"],
        water_outlet_quality=cycle["titulo_w_cond_out"], water_pressure_bar=p.P_w_cond,
        water_outlet_phase=cycle["fase_w_cond_out"], low_condensation_C=cycle["T_cd_l"],
        high_evaporation_C=cycle["T_ev_h"], low_evaporation_C=cycle["T_ev_l"],
        high_condensation_C=cycle["T_cd_h"], subcooler_heat_kW=high["Q_sc"] / 1000,
        energy_residual_W=cycle["Q_total"] - cycle["W_total"] - low["Q_ev"],
        cascade_residual_W=cycle["residual_cascade"], condenser_heat_kW=high["Q_cond"] / 1000,
        source_heat_kW=low["Q_ev"] / 1000, source_mass_flow_kg_s=cycle["m_dot_source"],
        water_mass_flow_kg_s=cycle["m_dot_w_cond"], pinch_condenser_K=p.DT_pinch_cond,
        pinch_cascade_K=p.DT_pinch_cascade, pinch_evaporator_K=p.DT_pinch_evap,
        pinch_subcooler_K=p.DT_pinch_sc, condenser_subcooling_low_K=p.SUB_l,
        condenser_subcooling_high_K=p.SUB_h,
        intermediate_pressures_optimized=p.optimize_injection,
        economizer_mass_fractions_optimized=cycle.get('economizer_mass_fractions_optimized',False),
        economizer_mass_fraction_mode=('optimized' if p.optimize_economizer_mass_fraction else
                                      'fixed' if p.fixed_economizer_mass_fraction else 'calculated'),
    )
    for prefix, stage, suffix in (("low", low, "l"), ("high", high, "h")):
        row[prefix + "_injection_pressure_bar"] = stage.get("P_int", "")
        row[prefix + "_injection_fraction"] = stage.get("injection_fraction", 0.0)
        row[prefix + '_economizer_pinch_K'] = stage.get('economizer_pinch_K','')
        row[prefix + '_economizer_required_UA_kW_K'] = stage.get('economizer_UA_kW_K','')
        row[prefix + "_discharge_C"] = stage["T2"]
        compressors = _compressors(stage, p, suffix)
        row[prefix + "_maximum_discharge_C"] = max(c["T_discharge"] for c in compressors)
        row[prefix + "_minimum_efficiency"] = min(c["eta_is"] for c in compressors)
        row[prefix + "_efficiency_limited"] = any(c["limited"] for c in compressors)
        for index, compressor in enumerate(compressors, 1):
            for key in ("RP", "eta_is", "eta_raw", "T_discharge"):
                row[f"{prefix}_compression_{index}_{key}"] = compressor[key]
    return row


def plot_curves(groups, xkey, ykey, xlabel, ylabel, title, path, p):
    fig, ax = plt.subplots()
    for index, (label, rows) in enumerate(groups):
        points = [row for row in rows if xkey in row]
        if points:
            ax.plot([row[xkey] for row in points],
                    [row.get(ykey, np.nan) if row["status"] == "valid" else np.nan
                     for row in points], color=COLORS[index % len(COLORS)],
                    linestyle=DASHES[index % len(DASHES)], marker=MARKERS[index % len(MARKERS)],
                    markersize=4,label=label)
    if p.MODO_AGUA_COND == "SATURADO":
        water_condition = f"saturated water at {p.T_sat_w_cond:g} °C"
    else:
        water_condition = (
            f"water {p.T_w_cond_in:g} °C at {p.P_w_cond_liq:g} bar"
        )
    source_condition = f"ambient air at {p.T_source_in:g} °C" if p.F_source == "Air" else f"source water at {p.T_source_in:g} °C"
    conditions = f"{p.Q_target / 1000:g} kW | {water_condition} | {source_condition}"
    ax.set(title=f"{title}\n{conditions}", xlabel=xlabel, ylabel=ylabel)
    add_minor_grid(ax)
    ax.legend(loc="best", ncols=2, fontsize=9)
    save_figure(fig, path)
    plt.close(fig)


def evaluate(label, p, temperature):
    try:
        cycle = model.ciclo_cascata(p, float(temperature))
        return record(label, p, cycle)
    except ValueError as error:
        return dict(configuration=label, status=failure_status(error), reason=str(error),
                    low_condensation_C=float(temperature), source_inlet_C=p.T_source_in,
                    with_high_stage_subcooler=p.use_subcooler)


def ph_analysis(p, cases, output_dir, cycles=None):
    """Plot the selected cycle stages using their calculated state points."""
    from hthp.plots.cycles.diagrams import plot_cycles

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
                if technology == "simple":
                    pairs = [(1, 2, "-"), (2, 3, "-"), (3, "3E", "-"), ("3E", 4, "-"), (4, 1, "-")]
                    main_loop = [1, 2, 3, "3E", 4]
                else:
                    pairs = [("1", "2", "-"), ("2", "3", "--"), ("3", "4", "-"),
                             ("4", "5", "-"), ("5", "5E", "-")]
                    if technology == "flash_tank":
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
