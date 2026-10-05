"""Analisa COP, temperatura ótima, descarga e limites de eficiência."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace

from analysis import settings
from analysis.common import configure_plot_style, save_csv
from analysis.integrated_pinch_model import (
    ARCHITECTURES,
    build_integrated_config,
    result_record,
)
from analysis.plot_style import COLORS, DASHES, finish_axis, save_standard_figure

import matplotlib.pyplot as plt

from hthp.cycles.integrated_pinch_cascade import (
    IntegratedPinchCascadeCycle,
    IntegratedPinchCascadeResult,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIRECTORY = PROJECT_ROOT / "results_pinch_point" / "curve_changes"


def _minimum(values: tuple[float, ...]) -> float:
    return min(values) if values else float("nan")


def _enrich_record(
    mode: str,
    result: IntegratedPinchCascadeResult,
    architecture: str,
    is_optimum: bool,
) -> dict:
    row = result_record(mode, result, is_optimum, architecture)
    row.update(
        {
            "low_stage_max_discharge_temperature_C": (
                result.low_stage.maximum_discharge_temperature_C
            ),
            "high_stage_max_discharge_temperature_C": (
                result.high_stage.stage.maximum_discharge_temperature_C
            ),
            "low_stage_min_raw_isentropic_efficiency": _minimum(
                result.low_stage.compressor_raw_isentropic_efficiencies
            ),
            "low_stage_min_applied_isentropic_efficiency": _minimum(
                result.low_stage.compressor_isentropic_efficiencies
            ),
            "high_stage_min_raw_isentropic_efficiency": _minimum(
                result.high_stage.stage.compressor_raw_isentropic_efficiencies
            ),
            "high_stage_min_applied_isentropic_efficiency": _minimum(
                result.high_stage.stage.compressor_isentropic_efficiencies
            ),
        }
    )
    return row


def _status_changes(architecture: str, rows: list[dict]) -> list[dict]:
    changes = []
    for previous, current in zip(rows, rows[1:]):
        previous_status = (
            previous["low_stage_compressor_efficiency_limit_statuses"],
            previous["high_stage_compressor_efficiency_limit_statuses"],
        )
        current_status = (
            current["low_stage_compressor_efficiency_limit_statuses"],
            current["high_stage_compressor_efficiency_limit_statuses"],
        )
        if previous_status == current_status:
            continue
        changes.append(
            {
                "architecture": architecture,
                "temperature_before_C": previous[
                    "high_stage_evaporation_temperature_C"
                ],
                "temperature_after_C": current[
                    "high_stage_evaporation_temperature_C"
                ],
                "COP_before": previous["overall_COP_electrical"],
                "COP_after": current["overall_COP_electrical"],
                "low_stage_status_before": previous_status[0],
                "low_stage_status_after": current_status[0],
                "high_stage_status_before": previous_status[1],
                "high_stage_status_after": current_status[1],
                "minimum_efficiency": settings.INTEGRATED_COMPRESSOR_EFFICIENCY_MIN,
            }
        )
    return changes


def _save_figures(curves: list[dict]) -> None:
    figure, axis = plt.subplots()
    for index, entry in enumerate(curves):
        rows = entry["rows"]
        x = [float(row["high_stage_evaporation_temperature_C"]) for row in rows]
        y = [float(row["overall_COP_electrical"]) for row in rows]
        axis.plot(
            x,
            y,
            color=COLORS[index],
            linestyle=DASHES[index],
            marker="none",
            label=entry["architecture"],
        )
        optimum = entry["optimum"]
        axis.scatter(
            [float(optimum["high_stage_evaporation_temperature_C"])],
            [float(optimum["overall_COP_electrical"])],
            color=COLORS[index],
            marker="o",
            s=28,
            zorder=4,
        )
        axis.axvline(
            float(optimum["high_stage_evaporation_temperature_C"]),
            color=COLORS[index],
            linewidth=0.8,
            alpha=0.30,
        )
    axis.set_xlabel("High-stage evaporation temperature [°C]")
    axis.set_ylabel("Overall electrical COP [-]")
    axis.set_title(
        "Cascade COP and continuous optima\n"
        f"{settings.HEATING_CAPACITY_KW:g} kW | water "
        f"{settings.INTEGRATED_WATER_MAIN_INLET_C:g}→"
        f"{settings.INTEGRATED_WATER_MAIN_OUTLET_C:g} °C"
    )
    finish_axis(axis)
    axis.legend(fontsize=7)
    save_standard_figure(
        figure, RESULTS_DIRECTORY / "01_COP_and_optima", settings.FIGURE_DPI
    )
    plt.close(figure)

    for stage, field, title in (
        ("low_stage", "low_stage_max_discharge_temperature_C", "Low stage"),
        ("high_stage", "high_stage_max_discharge_temperature_C", "High stage"),
    ):
        figure, axis = plt.subplots()
        for index, entry in enumerate(curves):
            rows = entry["rows"]
            x = [float(row["high_stage_evaporation_temperature_C"]) for row in rows]
            axis.plot(
                x,
                [float(row[field]) for row in rows],
                color=COLORS[index],
                linestyle=DASHES[index],
                marker="none",
                label=entry["architecture"],
            )
        axis.set_xlabel("High-stage evaporation temperature [°C]")
        axis.set_ylabel("Maximum compressor discharge temperature [°C]")
        axis.set_title(
            f"{title} | {settings.HEATING_CAPACITY_KW:g} kW | water "
            f"{settings.INTEGRATED_WATER_MAIN_INLET_C:g}→"
            f"{settings.INTEGRATED_WATER_MAIN_OUTLET_C:g} °C"
        )
        finish_axis(axis)
        axis.legend(fontsize=7)
        save_standard_figure(
            figure,
            RESULTS_DIRECTORY / f"02_{stage}_discharge_temperature",
            settings.FIGURE_DPI,
        )
        plt.close(figure)

    for stage, title in (("low_stage", "Low-stage compressor"), ("high_stage", "High-stage compressor")):
        figure, axis = plt.subplots()
        for index, entry in enumerate(curves):
            rows = entry["rows"]
            x = [float(row["high_stage_evaporation_temperature_C"]) for row in rows]
            raw_field = f"{stage}_min_raw_isentropic_efficiency"
            used_field = f"{stage}_min_applied_isentropic_efficiency"
            raw = [float(row[raw_field]) for row in rows]
            used = [float(row[used_field]) for row in rows]
            axis.plot(
                x,
                used,
                color=COLORS[index],
                linestyle=DASHES[index],
                marker="none",
                label=entry["architecture"],
            )
            if any(abs(a - b) > 1.0e-9 for a, b in zip(raw, used)):
                axis.plot(
                    x,
                    raw,
                    color=COLORS[index],
                    linestyle=":",
                    marker="none",
                    linewidth=1.1,
                    alpha=0.7,
                    label=f"{entry['architecture']} raw",
                )
        axis.axhline(
            settings.INTEGRATED_COMPRESSOR_EFFICIENCY_MIN,
            color="black",
            linestyle="--",
            linewidth=1.0,
            label="Minimum allowed efficiency",
        )
        axis.set_xlabel("High-stage evaporation temperature [°C]")
        axis.set_ylabel("Minimum isentropic efficiency [-]")
        axis.set_title(
            f"{title} | {settings.HEATING_CAPACITY_KW:g} kW | minimum ηis = "
            f"{settings.INTEGRATED_COMPRESSOR_EFFICIENCY_MIN:.2f}"
        )
        finish_axis(axis)
        axis.legend(fontsize=6.2, ncol=2)
        save_standard_figure(
            figure,
            RESULTS_DIRECTORY / f"03_{stage}_efficiency_limit",
            settings.FIGURE_DPI,
        )
        plt.close(figure)


def _unclipped_cop_curves() -> list[dict]:
    """Re-evaluate points while rejecting efficiencies outside the configured range."""

    curves = []
    step = settings.INTEGRATED_HIGH_EVAPORATION_STEP_K
    count = round(
        (settings.INTEGRATED_HIGH_EVAPORATION_MAX_C
         - settings.INTEGRATED_HIGH_EVAPORATION_MIN_C) / step
    )
    for architecture, low_technology, high_technology in ARCHITECTURES:
        config = replace(
            build_integrated_config("hot_water", low_technology, high_technology),
            reject_limited_compressor_efficiencies=True,
        )
        solver = IntegratedPinchCascadeCycle(config)
        points: list[tuple[float, float | None]] = []
        valid_points: list[tuple[float, float]] = []
        for index in range(count + 1):
            temperature = settings.INTEGRATED_HIGH_EVAPORATION_MIN_C + index * step
            try:
                result = solver.solve(
                    temperature + config.pinch_points.cascade_K
                )
            except (ValueError, OverflowError):
                points.append((temperature, None))
                continue
            point = (temperature, result.overall_COP_electrical)
            points.append(point)
            valid_points.append(point)
        curves.append(
            {
                "architecture": architecture,
                "points": points,
                "valid_points": valid_points,
            }
        )
    return curves


def _save_clipping_sensitivity(curves: list[dict]) -> None:
    unbounded_curves = _unclipped_cop_curves()
    figure, axis = plt.subplots()
    for index, (entry, valid_curve) in enumerate(zip(curves, unbounded_curves)):
        rows = entry["rows"]
        axis.plot(
            [float(row["high_stage_evaporation_temperature_C"]) for row in rows],
            [float(row["overall_COP_electrical"]) for row in rows],
            color=COLORS[index],
            linestyle=DASHES[index],
            marker="none",
            label=f"{entry['architecture']} — clipped model",
        )
        if len(valid_curve["valid_points"]) < len(valid_curve["points"]):
            x = [point[0] for point in valid_curve["points"]]
            y = [float("nan") if point[1] is None else point[1] for point in valid_curve["points"]]
            axis.plot(
                x,
                y,
                color=COLORS[index],
                linestyle="--",
                marker="none",
                linewidth=1.0,
                alpha=0.75,
                label=f"{entry['architecture']} — no clipping",
            )
    sensitivity_rows = []
    for curve in unbounded_curves:
        points = curve["points"]
        valid = curve["valid_points"]
        valid_temperatures = [temperature for temperature, _ in valid]
        sensitivity_rows.append(
            {
                "architecture": curve["architecture"],
                "grid_points": len(points),
                "points_within_efficiency_limits": len(valid),
                "points_rejected_for_efficiency_limits": len(points) - len(valid),
                "lowest_valid_high_stage_evaporation_C": (
                    min(valid_temperatures) if valid_temperatures else ""
                ),
                "highest_valid_high_stage_evaporation_C": (
                    max(valid_temperatures) if valid_temperatures else ""
                ),
                "interpretation": "COP retained only where raw compressor efficiency stays within configured limits",
            }
        )
    save_csv(
        sensitivity_rows,
        RESULTS_DIRECTORY / "efficiency_limit_sensitivity.csv",
    )
    axis.set_xlabel("High-stage evaporation temperature [°C]")
    axis.set_ylabel("Overall electrical COP [-]")
    axis.set_title(
        "Effect of compressor-efficiency clipping\n"
        f"{settings.HEATING_CAPACITY_KW:g} kW | ηis range "
        f"{settings.INTEGRATED_COMPRESSOR_EFFICIENCY_MIN:.2f}–"
        f"{settings.INTEGRATED_COMPRESSOR_EFFICIENCY_MAX:.2f}"
    )
    finish_axis(axis)
    axis.legend(
        fontsize=6.4,
        ncol=2,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.15),
    )
    save_standard_figure(
        figure,
        RESULTS_DIRECTORY / "04_COP_clipping_sensitivity",
        settings.FIGURE_DPI,
    )
    plt.close(figure)


def _write_report(curves: list[dict], status_changes: list[dict]) -> None:
    lines = [
        "# COP, compressor discharge and efficiency-limit study",
        "",
        "## Conditions",
        "",
        f"- Useful heating duty: {settings.HEATING_CAPACITY_KW:g} kW.",
        f"- Water: {settings.INTEGRATED_WATER_MAIN_INLET_C:g} to "
        f"{settings.INTEGRATED_WATER_MAIN_OUTLET_C:g} °C at "
        f"{settings.INTEGRATED_WATER_PRESSURE_BAR:g} bar.",
        f"- Source: {settings.INTEGRATED_SOURCE_INLET_C:g} to "
        f"{settings.INTEGRATED_SOURCE_OUTLET_C:g} °C.",
        f"- High-stage evaporation search: {settings.INTEGRATED_HIGH_EVAPORATION_MIN_C:g}–"
        f"{settings.INTEGRATED_HIGH_EVAPORATION_MAX_C:g} °C.",
        "- Compressor efficiency: the current linear correlation, clipped to its configured limits.",
        "- The discharge-temperature curves are model predictions; no manufacturer compressor map or allowable-temperature limit is applied.",
        "",
        "## Continuous optima",
        "",
        "| Configuration | T* high-stage evap. [°C] | COP* | Power [kW] | Max discharge low/high [°C] | Boundary? |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    for entry in curves:
        row = entry["optimum"]
        temperature = float(row["high_stage_evaporation_temperature_C"])
        at_boundary = min(
            abs(temperature - settings.INTEGRATED_HIGH_EVAPORATION_MIN_C),
            abs(temperature - settings.INTEGRATED_HIGH_EVAPORATION_MAX_C),
        ) <= settings.INTEGRATED_TEMPERATURE_OPTIMIZATION_TOLERANCE_K
        lines.append(
            f"| {entry['architecture']} | {temperature:.2f} | "
            f"{float(row['overall_COP_electrical']):.3f} | "
            f"{float(row['total_electrical_power_kW']):.2f} | "
            f"{float(row['low_stage_max_discharge_temperature_C']):.1f} / "
            f"{float(row['high_stage_max_discharge_temperature_C']):.1f} | "
            f"{'Yes' if at_boundary else 'No'} |"
        )
    lines.extend(
        [
            "",
            "## Effect of the efficiency lower limit",
            "",
            "| Configuration | Sweep points without active limit | Minimum raw efficiency low/high |",
            "|---|---:|---:|",
        ]
    )
    for entry in curves:
        rows = entry["rows"]
        valid_count = sum(
            not row["any_compressor_efficiency_limit_active"] for row in rows
        )
        raw_low = [
            float(value)
            for row in rows
            for value in row["low_stage_compressor_raw_isentropic_efficiencies"].split("|")
            if value
        ]
        raw_high = [
            float(value)
            for row in rows
            for value in row["high_stage_compressor_raw_isentropic_efficiencies"].split("|")
            if value
        ]
        lines.append(
            f"| {entry['architecture']} | {valid_count}/{len(rows)} | "
            f"{min(raw_low):.3f} / {min(raw_high):.3f} |"
        )
    lines.extend(
        [
            "",
            "## Efficiency-limit transitions",
            "",
        ]
    )
    if status_changes:
        lines.extend(
            [
                "| Configuration | Temperature interval [°C] | Low-stage status | High-stage status |",
                "|---|---:|---|---|",
            ]
        )
        for row in status_changes:
            lines.append(
                f"| {row['architecture']} | {float(row['temperature_before_C']):.1f}–"
                f"{float(row['temperature_after_C']):.1f} | "
                f"{row['low_stage_status_before']} → {row['low_stage_status_after']} | "
                f"{row['high_stage_status_before']} → {row['high_stage_status_after']} |"
            )
    else:
        lines.append("No compressor-efficiency clipping transition was detected on the sampled curves.")
    lines.extend(
        [
            "",
            "The clipped-model COP curve includes every thermodynamic point and substitutes the configured efficiency limit when the raw correlation exceeds its range. The clipping-sensitivity figure overlays a second calculation that rejects such points, leaving gaps where the efficiency correlation is outside its configured range. A kink near a limit transition is therefore partly caused by the chosen efficiency correlation and clipping rule. This rejection check evaluates the assumed correlation only; it is not a manufacturer compressor map. Compare predicted discharge temperatures against the actual compressor manufacturer's allowable envelope before making an equipment-feasibility claim.",
            "",
        ]
    )
    (RESULTS_DIRECTORY / "curve_change_report.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main() -> None:
    configure_plot_style()
    RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    curves: list[dict] = []
    all_rows: list[dict] = []
    optima: list[dict] = []
    status_changes: list[dict] = []

    for architecture, low_technology, high_technology in ARCHITECTURES:
        optimization = IntegratedPinchCascadeCycle(
            build_integrated_config("hot_water", low_technology, high_technology)
        ).optimize_intermediate_temperature()
        rows = [
            _enrich_record("hot_water", result, architecture, False)
            for result in optimization.valid_points
        ]
        optimum = _enrich_record(
            "hot_water", optimization.optimum, architecture, True
        )
        optimum.update(
            {
                "optimization_method": optimization.optimization_method,
                "function_evaluations": optimization.function_evaluations,
                "temperature_tolerance_K": (
                    settings.INTEGRATED_TEMPERATURE_OPTIMIZATION_TOLERANCE_K
                ),
                "optimum_at_temperature_boundary": (
                    optimization.optimum_at_temperature_boundary
                ),
            }
        )
        curves.append({"architecture": architecture, "rows": rows, "optimum": optimum})
        all_rows.extend(rows)
        optima.append(optimum)
        status_changes.extend(_status_changes(architecture, rows))

    save_csv(all_rows, RESULTS_DIRECTORY / "curve_points.csv")
    save_csv(optima, RESULTS_DIRECTORY / "continuous_optima.csv")
    save_csv(status_changes, RESULTS_DIRECTORY / "efficiency_limit_transitions.csv")
    _save_figures(curves)
    _save_clipping_sensitivity(curves)
    _write_report(curves, status_changes)
    print(f"COP and compressor analysis: results in {RESULTS_DIRECTORY}")


if __name__ == "__main__":
    main()
