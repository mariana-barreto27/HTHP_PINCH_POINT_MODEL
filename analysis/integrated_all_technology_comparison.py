"""Compara flash tank e economizador no modelo integrado de pinch."""

from __future__ import annotations

from pathlib import Path

from analysis import settings
from analysis.common import configure_plot_style, save_csv
from analysis.integrated_pinch_model import build_integrated_config, result_record
from analysis.plot_style import COLORS, DASHES, finish_axis, save_standard_figure

import matplotlib.pyplot as plt

from hthp.cycles.integrated_pinch_cascade import IntegratedPinchCascadeCycle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIRECTORY = (
    PROJECT_ROOT / "results_pinch_point" / "technology_comparison"
)

ARCHITECTURES = (
    ("Conventional cascade", "simple", "simple"),
    ("Low-stage flash tank", "flash_tank", "simple"),
    ("High-stage flash tank", "simple", "flash_tank"),
    ("Flash tanks in both stages", "flash_tank", "flash_tank"),
    ("Low-stage economizer", "economizer", "simple"),
    ("High-stage economizer", "simple", "economizer"),
    ("Economizers in both stages", "economizer", "economizer"),
)


def main() -> None:
    configure_plot_style()
    RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    sink_mode = "hot_water"
    curves: list[tuple[str, list[dict]]] = []
    all_rows: list[dict] = []
    optimum_rows: list[dict] = []

    for architecture, low_technology, high_technology in ARCHITECTURES:
        optimization = IntegratedPinchCascadeCycle(
            build_integrated_config(
                sink_mode,
                low_technology,
                high_technology,
            )
        ).optimize_intermediate_temperature()
        optimum = optimization.optimum
        rows = [
            result_record(
                sink_mode,
                result,
                result is optimum,
                architecture,
            )
            for result in optimization.valid_points
        ]
        curves.append((architecture, rows))
        all_rows.extend(rows)
        optimum_rows.append(
            result_record(
                sink_mode,
                optimum,
                True,
                architecture,
            )
        )

    save_csv(all_rows, RESULTS_DIRECTORY / "all_technology_sweep.csv")
    save_csv(
        optimum_rows,
        RESULTS_DIRECTORY / "all_technology_optimum_summary.csv",
    )

    figure, axis = plt.subplots()
    for index, (architecture, rows) in enumerate(curves):
        axis.plot(
            [
                float(row["high_stage_evaporation_temperature_C"])
                for row in rows
            ],
            [float(row["overall_COP_electrical"]) for row in rows],
            color=COLORS[index],
            linestyle=DASHES[index],
            marker="none",
            label=architecture,
        )
    axis.set_xlabel("High-stage evaporation temperature [°C]")
    axis.set_ylabel("Overall COP [-]")
    axis.set_title(
        "Cascade COP — Flash tank and economizer comparison\n"
        f"{settings.HEATING_CAPACITY_KW:g} kW | "
        f"water {settings.INTEGRATED_WATER_MAIN_INLET_C:g}→"
        f"{settings.INTEGRATED_WATER_MAIN_OUTLET_C:g} °C"
    )
    finish_axis(axis)
    axis.legend(ncol=2, fontsize=6.5)
    save_standard_figure(
        figure,
        RESULTS_DIRECTORY / "01_all_COP_comparison",
        settings.FIGURE_DPI,
    )
    plt.close(figure)

    print(f"Technology comparison: results in {RESULTS_DIRECTORY}")


if __name__ == "__main__":
    main()