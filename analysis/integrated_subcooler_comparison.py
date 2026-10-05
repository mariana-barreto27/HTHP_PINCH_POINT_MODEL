"""Compara flash tank e economizador com e sem o subcooler externo."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from analysis import settings
from analysis.common import configure_plot_style, save_csv
from analysis.integrated_all_technology_comparison import ARCHITECTURES
from analysis.integrated_pinch_model import build_integrated_config, result_record
from analysis.plot_style import COLORS, DASHES, finish_axis, save_standard_figure
from hthp.cycles.integrated_pinch_cascade import IntegratedPinchCascadeCycle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIRECTORY = (
    PROJECT_ROOT / "results_pinch_point" / "subcooler_comparison"
)


def calculate_comparison() -> dict[str, list[tuple[str, list[dict]]]]:
    cases: dict[str, list[tuple[str, list[dict]]]] = {}
    all_rows: list[dict] = []
    for case, effectiveness in (
        ("with_high_stage_subcooler", settings.INTEGRATED_EXTERNAL_SUBCOOLER_EFFECTIVENESS),
        ("without_external_subcooler", 0.0),
    ):
        curves: list[tuple[str, list[dict]]] = []
        for architecture, low_technology, high_technology in ARCHITECTURES:
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
                    architecture,
                )
                for result in optimization.valid_points
            ]
            for row in rows:
                row["subcooler_case"] = case
                row["external_subcooler_effectiveness"] = effectiveness
            curves.append((architecture, rows))
            all_rows.extend(rows)
        cases[case] = curves
    save_csv(all_rows, RESULTS_DIRECTORY / "subcooler_comparison.csv")
    return cases


def _plot_case(
    curves: list[tuple[str, list[dict]]],
    *,
    title: str,
    output_name: str,
) -> None:
    figure, axis = plt.subplots(figsize=(8.8, 5.4))
    for index, (architecture, rows) in enumerate(curves):
        axis.plot(
            [float(row["high_stage_evaporation_temperature_C"]) for row in rows],
            [float(row["overall_COP_electrical"]) for row in rows],
            color=COLORS[index],
            linestyle=DASHES[index],
            marker="none",
            label=architecture,
        )
    axis.set_xlabel("High-stage evaporation temperature [°C]")
    axis.set_ylabel("Overall electrical COP [-]")
    axis.set_title(
        f"{title}\n"
        f"{settings.HEATING_CAPACITY_KW:g} kW | water "
        f"{settings.INTEGRATED_WATER_MAIN_INLET_C:g}→"
        f"{settings.INTEGRATED_WATER_MAIN_OUTLET_C:g} °C"
    )
    finish_axis(axis)
    axis.legend(ncol=2, fontsize=6.5)
    save_standard_figure(
        figure,
        RESULTS_DIRECTORY / output_name,
        settings.FIGURE_DPI,
    )
    plt.close(figure)


def main() -> None:
    configure_plot_style()
    RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    cases = calculate_comparison()
    _plot_case(
        cases["with_high_stage_subcooler"],
        title="Cascade COP — High-stage external subcooler active",
        output_name="01_COP_with_high_stage_subcooler",
    )
    _plot_case(
        cases["without_external_subcooler"],
        title="Cascade COP — Without external subcooler",
        output_name="02_COP_without_external_subcooler",
    )
    print(f"Subcooler comparison: results in {RESULTS_DIRECTORY}")


if __name__ == "__main__":
    main()
