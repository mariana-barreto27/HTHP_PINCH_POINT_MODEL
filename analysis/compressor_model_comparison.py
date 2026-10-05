"""Compara três hipóteses de eficiência usando o mesmo ciclo integrado."""

from __future__ import annotations

from pathlib import Path

from analysis import settings
from analysis.common import configure_plot_style, save_csv
from analysis.integrated_pinch_model import (
    ARCHITECTURES,
    MODE_LABELS,
    build_integrated_config,
    result_record,
)
from analysis.plot_style import COLORS, DASHES, finish_axis, save_standard_figure

import matplotlib.pyplot as plt

from hthp.cycles.integrated_pinch_cascade import IntegratedPinchCascadeCycle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIRECTORY = (
    PROJECT_ROOT / "results_pinch_point" / "compressor_models"
)
MODEL_CASES = (
    (
        "constant",
        "Constant efficiency",
        "Cascade COP — constant compressor efficiency",
    ),
    (
        "reference_quadratic",
        "Reference quadratic correlations",
        "Cascade COP — quadratic efficiency equation",
    ),
    (
        "linear",
        "Linear efficiency",
        "Cascade COP — linear compressor efficiency",
    ),
)


def main() -> None:
    configure_plot_style()
    RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    sink_mode = settings.COMPRESSOR_MODEL_COMPARISON_SINK_MODE
    model_curves: dict[str, list[tuple[str, list[dict]]]] = {}
    summary: list[dict] = []
    all_cop_values: list[float] = []

    for model_key, model_label, _ in MODEL_CASES:
        architecture_curves: list[tuple[str, list[dict]]] = []
        model_rows: list[dict] = []
        for architecture, low_technology, high_technology in ARCHITECTURES:
            config = build_integrated_config(
                sink_mode,
                low_technology,
                high_technology,
                compressor_efficiency_mode=model_key,
            )
            optimization = IntegratedPinchCascadeCycle(
                config
            ).optimize_intermediate_temperature()
            optimum = optimization.optimum
            rows = [
                {
                    **result_record(
                        sink_mode,
                        result,
                        result is optimum,
                        architecture,
                    ),
                    "comparison_model": model_key,
                    "comparison_model_label": model_label,
                }
                for result in optimization.valid_points
            ]
            architecture_curves.append((architecture, rows))
            model_rows.extend(rows)
            all_cop_values.extend(
                float(row["overall_COP_electrical"]) for row in rows
            )
            summary.append(
                {
                    **result_record(
                        sink_mode,
                        optimum,
                        True,
                        architecture,
                    ),
                    "comparison_model": model_key,
                    "comparison_model_label": model_label,
                    "optimum_at_boundary": (
                        optimization.optimum_at_temperature_boundary
                    ),
                }
            )
        save_csv(
            model_rows,
            RESULTS_DIRECTORY / f"{model_key}_temperature_sweep.csv",
        )
        model_curves[model_key] = architecture_curves

    y_min = min(all_cop_values)
    y_max = max(all_cop_values)
    y_padding = 0.04 * (y_max - y_min)
    for figure_number, (model_key, _, title) in enumerate(
        MODEL_CASES,
        start=1,
    ):
        figure, axis = plt.subplots()
        for index, (architecture, rows) in enumerate(model_curves[model_key]):
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
        axis.set_title(title)
        axis.set_ylim(y_min - y_padding, y_max + y_padding)
        finish_axis(axis)
        axis.legend(ncol=2, fontsize=7)
        save_standard_figure(
            figure,
            RESULTS_DIRECTORY
            / f"{figure_number:02d}_{model_key}_architecture_comparison",
            settings.FIGURE_DPI,
        )
        plt.close(figure)

    save_csv(summary, RESULTS_DIRECTORY / "optimum_summary.csv")
    print(
        "Compressor-model comparison "
        f"({MODE_LABELS[sink_mode]}): results in {RESULTS_DIRECTORY}"
    )


if __name__ == "__main__":
    main()
