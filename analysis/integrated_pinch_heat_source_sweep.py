"""Compara o COP ao variar a entrada da fonte com evaporação fixa."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from analysis import settings
from analysis.common import configure_plot_style, report_completion, save_csv
from analysis.integrated_pinch_model import (
    build_integrated_config,
    result_record,
)
from analysis.integrated_all_technology_comparison import (
    ARCHITECTURES as ALL_TECHNOLOGY_ARCHITECTURES,
)
from analysis.plot_style import COLORS, DASHES, finish_axis, save_standard_figure

from hthp.cycles.integrated_pinch_cascade import IntegratedPinchCascadeCycle
from hthp.heat_sources.pinch_stream import PinchStreamHeatSource


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIRECTORY = (
    PROJECT_ROOT
    / "results_pinch_point"
    / "heat_source_temperature_fixed_evaporation"
)

# Os valores-padrão permitem copiar somente este arquivo para uma versão do
# projeto cujo settings.py ainda não tenha as opções específicas do gráfico.
SOURCE_TEMPERATURE_DROP_K = getattr(
    settings,
    "INTEGRATED_SOURCE_TEMPERATURE_DROP_K",
    settings.INTEGRATED_SOURCE_INLET_C - settings.INTEGRATED_SOURCE_OUTLET_C,
)
SOURCE_INLET_MIN_C = getattr(
    settings,
    "INTEGRATED_MAP_SOURCE_INLET_MIN_C",
    0.0,
)
SOURCE_INLET_MAX_C = getattr(
    settings,
    "INTEGRATED_MAP_SOURCE_INLET_MAX_C",
    40.0,
)
SOURCE_INLET_POINTS = getattr(
    settings,
    "INTEGRATED_MAP_SOURCE_INLET_POINTS",
    17,
)
FIXED_HIGH_EVAPORATION_C = getattr(
    settings,
    "INTEGRATED_HEAT_SOURCE_SWEEP_FIXED_HIGH_EVAPORATION_C",
    35.0,
)


def _heat_source(source_inlet_temperature_C: float) -> PinchStreamHeatSource:
    return PinchStreamHeatSource(
        inlet_temperature_C=source_inlet_temperature_C,
        outlet_temperature_C=(
            source_inlet_temperature_C - SOURCE_TEMPERATURE_DROP_K
        ),
        evaporator_pinch_K=settings.INTEGRATED_PINCH_EVAPORATOR_K,
        pressure_bar=settings.INTEGRATED_SOURCE_PRESSURE_BAR,
        fluid=settings.INTEGRATED_SOURCE_FLUID,
    )


def calculate_sweep(
    source_inlet_values_C: np.ndarray,
) -> list[dict[str, float | bool | str]]:
    """Resolve todas as arquiteturas mantendo a evaporação de alta fixa."""

    records: list[dict[str, float | bool | str]] = []
    low_condensation_C = (
        FIXED_HIGH_EVAPORATION_C + settings.INTEGRATED_PINCH_CASCADE_K
    )

    for (
        architecture,
        low_technology,
        high_technology,
    ) in ALL_TECHNOLOGY_ARCHITECTURES:
        base_config = build_integrated_config(
            "hot_water",
            low_technology,
            high_technology,
            compressor_efficiency_mode="linear",
        )
        for source_inlet_C in source_inlet_values_C:
            source = _heat_source(float(source_inlet_C))
            common = {
                "architecture": architecture,
                "valid": False,
                "error": "",
                "sweep_heat_source_inlet_temperature_C": float(
                    source_inlet_C
                ),
                "sweep_heat_source_outlet_temperature_C": (
                    source.outlet_temperature_C
                ),
                "sweep_low_stage_evaporation_temperature_C": (
                    source.evaporation_temperature_C()
                ),
                "fixed_high_stage_evaporation_temperature_C": (
                    FIXED_HIGH_EVAPORATION_C
                ),
                "fixed_low_stage_condensation_temperature_C": (
                    low_condensation_C
                ),
                "source_temperature_drop_K": SOURCE_TEMPERATURE_DROP_K,
            }
            try:
                result = IntegratedPinchCascadeCycle(
                    replace(base_config, external_heat_source=source)
                ).solve(low_condensation_C)
                record = result_record(
                    "hot_water",
                    result,
                    False,
                    architecture,
                )
                record.update(common)
                record["valid"] = True
            except (ValueError, OverflowError) as error:
                record = dict(common)
                record["error"] = f"{type(error).__name__}: {error}"
            records.append(record)

    return records


def save_cop_chart(
    records: list[dict[str, float | bool | str]],
    output: Path,
) -> None:
    """Salva todas as arquiteturas em um único gráfico comparativo."""

    figure, axis = plt.subplots(figsize=(8.8, 5.4))
    for index, (architecture, _, _) in enumerate(
        ALL_TECHNOLOGY_ARCHITECTURES
    ):
        selected = [
            record
            for record in records
            if record["architecture"] == architecture and record["valid"]
        ]
        axis.plot(
            [
                float(record["sweep_heat_source_inlet_temperature_C"])
                for record in selected
            ],
            [float(record["overall_COP_electrical"]) for record in selected],
            label=architecture,
            color=COLORS[index],
            linestyle=DASHES[index],
            marker="none",
        )

    axis.set_xlabel("Ambient-air inlet temperature [°C]")
    axis.set_ylabel("Overall electrical COP [-]")
    axis.set_title(
        "Cascade COP — Ambient-air inlet temperature\n"
        f"{settings.HEATING_CAPACITY_KW:g} kW | "
        f"High-stage evaporation = {FIXED_HIGH_EVAPORATION_C:g} °C | "
        f"Water {settings.INTEGRATED_WATER_MAIN_INLET_C:g}→"
        f"{settings.INTEGRATED_WATER_MAIN_OUTLET_C:g} °C"
    )
    axis.set_xlim(SOURCE_INLET_MIN_C, SOURCE_INLET_MAX_C)
    finish_axis(axis)
    axis.legend(ncol=2, fontsize=7.5, handlelength=2.2, columnspacing=0.8)
    save_standard_figure(figure, output, settings.FIGURE_DPI)
    plt.close(figure)


def main() -> None:
    configure_plot_style()
    RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    source_inlet_values_C = np.linspace(
        SOURCE_INLET_MIN_C,
        SOURCE_INLET_MAX_C,
        SOURCE_INLET_POINTS,
    )
    records = calculate_sweep(source_inlet_values_C)
    save_csv(records, RESULTS_DIRECTORY / "heat_source_temperature_sweep.csv")
    save_cop_chart(
        records,
        RESULTS_DIRECTORY / "01_COP_vs_heat_source_inlet_temperature",
    )
    report_completion(
        "Fonte térmica com evaporação de alta fixa",
        records,
        RESULTS_DIRECTORY,
    )


if __name__ == "__main__":
    main()
