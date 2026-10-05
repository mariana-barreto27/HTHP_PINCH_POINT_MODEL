"""Compara economizadores nos estágios da cascata integrada."""

from __future__ import annotations

from pathlib import Path

from analysis import settings
from analysis.common import configure_plot_style, save_csv
from analysis.integrated_pinch_model import build_integrated_config, result_record
from analysis.plot_style import COLORS, finish_axis, save_standard_figure

import matplotlib.pyplot as plt

from hthp.cycles.integrated_pinch_cascade import IntegratedPinchCascadeCycle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIRECTORY = PROJECT_ROOT / "results_pinch_point" / "economizer"

ECONOMIZER_ARCHITECTURES = (
    ("Conventional cascade", "simple", "simple"),
    ("Low-stage economizer", "economizer", "simple"),
    ("High-stage economizer", "simple", "economizer"),
    ("Economizers in both stages", "economizer", "economizer"),
)


def main() -> None:
    configure_plot_style()
    RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    sink_mode = "hot_water"
    curves: list[tuple[str, list[dict], str]] = []
    summary: list[dict] = []

    cases = (
        ("without subcooler", 0.0, "--"),
        (
            "with high-stage subcooler",
            settings.INTEGRATED_EXTERNAL_SUBCOOLER_EFFECTIVENESS,
            "-",
        ),
    )
    for architecture, low_technology, high_technology in ECONOMIZER_ARCHITECTURES:
        for subcooler_label, effectiveness, linestyle in cases:
            complete_label = f"{architecture} — {subcooler_label}"
            solver = IntegratedPinchCascadeCycle(
                build_integrated_config(
                    sink_mode,
                    low_technology,
                    high_technology,
                    compressor_efficiency_mode="linear",
                    external_subcooler_effectiveness=effectiveness,
                )
            )
            optimization = solver.optimize_intermediate_temperature()
            optimum = optimization.optimum
            rows = [
                result_record(
                    sink_mode,
                    result,
                    result is optimum,
                    complete_label,
                )
                for result in optimization.valid_points
            ]
            for row in rows:
                row["subcooler_case"] = subcooler_label
            curves.append((complete_label, rows, linestyle))
            optimum_row = result_record(
                sink_mode, optimum, True, complete_label
            )
            optimum_row["subcooler_case"] = subcooler_label
            summary.append(optimum_row)

    save_csv(summary, RESULTS_DIRECTORY / "economizer_optimum_summary.csv")

    figure, axis = plt.subplots()
    for index, (architecture, rows, linestyle) in enumerate(curves):
        axis.plot(
            [
                float(row["high_stage_evaporation_temperature_C"])
                for row in rows
            ],
            [float(row["overall_COP_electrical"]) for row in rows],
            color=COLORS[index // 2],
            linestyle=linestyle,
            marker="none",
            label=architecture,
        )
    axis.set_xlabel("High-stage evaporation temperature [°C]")
    axis.set_ylabel("Overall COP [-]")
    axis.set_title(
        "Cascade COP — Economizer vapor injection\n"
        f"{settings.HEATING_CAPACITY_KW:g} kW | "
        f"water {settings.INTEGRATED_WATER_MAIN_INLET_C:g}→"
        f"{settings.INTEGRATED_WATER_MAIN_OUTLET_C:g} °C"
    )
    finish_axis(axis)
    axis.legend(ncol=2, fontsize=6.2)
    save_standard_figure(
        figure,
        RESULTS_DIRECTORY / "01_economizer_architecture_comparison",
        settings.FIGURE_DPI,
    )
    plt.close(figure)

    print(f"Economizer analysis: results in {RESULTS_DIRECTORY}")


if __name__ == "__main__":
    main()
