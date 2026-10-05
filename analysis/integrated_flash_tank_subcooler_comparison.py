"""Compara flash tanks com e sem o subcooler externo do estágio alto."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from analysis import settings
from analysis.common import configure_plot_style, save_csv
from analysis.integrated_pinch_model import build_integrated_config, result_record
from analysis.plot_style import COLORS, finish_axis, save_standard_figure
from hthp.cycles.integrated_pinch_cascade import IntegratedPinchCascadeCycle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIRECTORY = PROJECT_ROOT / "results_pinch_point" / "flash_tank"
ARCHITECTURES = (
    ("Conventional cascade", "simple", "simple"),
    ("Low-stage flash tank", "flash_tank", "simple"),
    ("High-stage flash tank", "simple", "flash_tank"),
    ("Flash tanks in both stages", "flash_tank", "flash_tank"),
)


def main() -> None:
    configure_plot_style()
    RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    curves: list[tuple[str, list[dict], str]] = []
    all_rows: list[dict] = []
    cases = (
        ("without subcooler", 0.0, "--"),
        (
            "with high-stage subcooler",
            settings.INTEGRATED_EXTERNAL_SUBCOOLER_EFFECTIVENESS,
            "-",
        ),
    )
    for architecture, low_technology, high_technology in ARCHITECTURES:
        for subcooler_label, effectiveness, linestyle in cases:
            label = f"{architecture} — {subcooler_label}"
            optimization = IntegratedPinchCascadeCycle(
                build_integrated_config(
                    "hot_water",
                    low_technology,
                    high_technology,
                    compressor_efficiency_mode="linear",
                    external_subcooler_effectiveness=effectiveness,
                )
            ).optimize_intermediate_temperature()
            rows = [
                result_record(
                    "hot_water",
                    result,
                    result is optimization.optimum,
                    label,
                )
                for result in optimization.valid_points
            ]
            for row in rows:
                row["subcooler_case"] = subcooler_label
            curves.append((label, rows, linestyle))
            all_rows.extend(rows)

    save_csv(all_rows, RESULTS_DIRECTORY / "flash_tank_subcooler_comparison.csv")
    figure, axis = plt.subplots()
    for index, (label, rows, linestyle) in enumerate(curves):
        axis.plot(
            [float(row["high_stage_evaporation_temperature_C"]) for row in rows],
            [float(row["overall_COP_electrical"]) for row in rows],
            color=COLORS[index // 2],
            linestyle=linestyle,
            marker="none",
            label=label,
        )
    axis.set_xlabel("High-stage evaporation temperature [°C]")
    axis.set_ylabel("Overall COP [-]")
    axis.set_title(
        "Cascade COP — Flash tank comparison\n"
        f"{settings.HEATING_CAPACITY_KW:g} kW | water "
        f"{settings.INTEGRATED_WATER_MAIN_INLET_C:g}→"
        f"{settings.INTEGRATED_WATER_MAIN_OUTLET_C:g} °C"
    )
    finish_axis(axis)
    axis.legend(ncol=2, fontsize=6.2)
    save_standard_figure(
        figure,
        RESULTS_DIRECTORY / "01_flash_tank_with_and_without_subcooler",
        settings.FIGURE_DPI,
    )
    plt.close(figure)
    print(f"Flash-tank comparison: results in {RESULTS_DIRECTORY}")


if __name__ == "__main__":
    main()
