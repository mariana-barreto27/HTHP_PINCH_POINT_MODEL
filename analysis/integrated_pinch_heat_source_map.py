"""Mapas de COP por fonte térmica e evaporação do estágio alto."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re

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
from analysis.plot_style import (
    HOUSE_DIVERGING,
    finish_axis,
    save_standard_figure,
)

from hthp.cycles.integrated_pinch_cascade import IntegratedPinchCascadeCycle
from hthp.heat_sources.pinch_stream import PinchStreamHeatSource


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIRECTORY = (
    PROJECT_ROOT
    / "results_pinch_point"
    / "maps"
    / "heat_source_vs_high_stage_evaporation"
)
# Compatibilidade com cópias do projeto cujo settings.py ainda não recebeu
# as opções específicas deste mapa.
SOURCE_TEMPERATURE_DROP_K = getattr(
    settings,
    "INTEGRATED_SOURCE_TEMPERATURE_DROP_K",
    settings.INTEGRATED_SOURCE_INLET_C - settings.INTEGRATED_SOURCE_OUTLET_C,
)
MAP_SOURCE_INLET_MIN_C = getattr(
    settings,
    "INTEGRATED_MAP_SOURCE_INLET_MIN_C",
    0.0,
)
MAP_SOURCE_INLET_MAX_C = getattr(
    settings,
    "INTEGRATED_MAP_SOURCE_INLET_MAX_C",
    40.0,
)
MAP_SOURCE_INLET_POINTS = getattr(
    settings,
    "INTEGRATED_MAP_SOURCE_INLET_POINTS",
    17,
)
MAP_HIGH_EVAPORATION_POINTS = getattr(
    settings,
    "INTEGRATED_MAP_HIGH_EVAPORATION_POINTS",
    17,
)


def _filename_slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def _heat_source(source_inlet_temperature_C: float) -> PinchStreamHeatSource:
    return PinchStreamHeatSource(
        inlet_temperature_C=source_inlet_temperature_C,
        outlet_temperature_C=(
            source_inlet_temperature_C
            - SOURCE_TEMPERATURE_DROP_K
        ),
        evaporator_pinch_K=settings.INTEGRATED_PINCH_EVAPORATOR_K,
        pressure_bar=settings.INTEGRATED_SOURCE_PRESSURE_BAR,
        fluid=settings.INTEGRATED_SOURCE_FLUID,
    )


def calculate_cop_maps(
    source_inlet_values_C: np.ndarray,
    high_stage_evaporation_values_C: np.ndarray,
) -> tuple[
    dict[str, np.ndarray],
    list[dict[str, float | bool | str]],
]:
    """Calcula uma matriz de COP para cada arquitetura integrada."""

    matrices: dict[str, np.ndarray] = {}
    records: list[dict[str, float | bool | str]] = []

    for (
        architecture,
        low_technology,
        high_technology,
    ) in ALL_TECHNOLOGY_ARCHITECTURES:
        matrix = np.full(
            (
                len(high_stage_evaporation_values_C),
                len(source_inlet_values_C),
            ),
            np.nan,
        )
        base_config = build_integrated_config(
            "hot_water",
            low_technology,
            high_technology,
            compressor_efficiency_mode="linear",
        )
        for row, high_evaporation_C in enumerate(
            high_stage_evaporation_values_C
        ):
            low_condensation_C = (
                float(high_evaporation_C)
                + settings.INTEGRATED_PINCH_CASCADE_K
            )
            for column, source_inlet_C in enumerate(source_inlet_values_C):
                source = _heat_source(float(source_inlet_C))
                common = {
                    "architecture": architecture,
                    "valid": False,
                    "error": "",
                    "map_heat_source_inlet_temperature_C": float(
                        source_inlet_C
                    ),
                    "map_heat_source_outlet_temperature_C": (
                        source.outlet_temperature_C
                    ),
                    "map_low_stage_evaporation_temperature_C": (
                        source.evaporation_temperature_C()
                    ),
                    "map_high_stage_evaporation_temperature_C": float(
                        high_evaporation_C
                    ),
                    "map_low_stage_condensation_temperature_C": (
                        low_condensation_C
                    ),
                    "source_temperature_drop_K": (
                        SOURCE_TEMPERATURE_DROP_K
                    ),
                }
                try:
                    result = IntegratedPinchCascadeCycle(
                        replace(
                            base_config,
                            external_heat_source=source,
                        )
                    ).solve(low_condensation_C)
                    record = result_record(
                        "hot_water",
                        result,
                        False,
                        architecture,
                    )
                    record.update(common)
                    record["valid"] = True
                    matrix[row, column] = result.overall_COP_electrical
                except (ValueError, OverflowError) as error:
                    record = dict(common)
                    record["error"] = f"{type(error).__name__}: {error}"
                records.append(record)
        matrices[architecture] = matrix

    return matrices, records


def maximum_cop_envelope(
    source_inlet_values_C: np.ndarray,
    high_stage_evaporation_values_C: np.ndarray,
    matrices: dict[str, np.ndarray],
) -> tuple[np.ndarray, list[dict[str, float | bool | str]]]:
    """Cria o envelope do maior COP válido em cada ponto da malha."""

    labels = [
        architecture
        for architecture, _, _ in ALL_TECHNOLOGY_ARCHITECTURES
    ]
    stack = np.stack([matrices[label] for label in labels])
    maximum_matrix = np.full(stack.shape[1:], np.nan)
    records: list[dict[str, float | bool | str]] = []

    for row, high_evaporation_C in enumerate(
        high_stage_evaporation_values_C
    ):
        for column, source_inlet_C in enumerate(source_inlet_values_C):
            values = stack[:, row, column]
            valid_indices = np.flatnonzero(np.isfinite(values))
            if valid_indices.size:
                selected_index = int(
                    valid_indices[np.argmax(values[valid_indices])]
                )
                maximum_cop = float(values[selected_index])
                selected_configuration = labels[selected_index]
                maximum_matrix[row, column] = maximum_cop
                valid = True
            else:
                maximum_cop = float("nan")
                selected_configuration = ""
                valid = False
            records.append(
                {
                    "heat_source_inlet_temperature_C": float(source_inlet_C),
                    "heat_source_outlet_temperature_C": (
                        float(source_inlet_C)
                        - SOURCE_TEMPERATURE_DROP_K
                    ),
                    "low_stage_evaporation_temperature_C": (
                        float(source_inlet_C)
                        - SOURCE_TEMPERATURE_DROP_K
                        - settings.INTEGRATED_PINCH_EVAPORATOR_K
                    ),
                    "high_stage_evaporation_temperature_C": float(
                        high_evaporation_C
                    ),
                    "selected_configuration": selected_configuration,
                    "maximum_overall_COP_electrical": maximum_cop,
                    "valid": valid,
                }
            )

    return maximum_matrix, records


def _save_map(
    source_inlet_values_C: np.ndarray,
    high_stage_evaporation_values_C: np.ndarray,
    matrix: np.ndarray,
    *,
    title: str,
    path: Path,
    common_minimum: float,
    common_maximum: float,
) -> None:
    figure, axis = plt.subplots(figsize=(8.8, 5.4))
    masked_matrix = np.ma.masked_invalid(matrix)
    image = axis.pcolormesh(
        source_inlet_values_C,
        high_stage_evaporation_values_C,
        masked_matrix,
        shading="auto",
        cmap=HOUSE_DIVERGING,
        vmin=common_minimum,
        vmax=common_maximum,
        rasterized=True,
    )

    finite_values = matrix[np.isfinite(matrix)]
    if finite_values.size and not np.isclose(
        float(np.min(finite_values)),
        float(np.max(finite_values)),
    ):
        contour_levels = np.linspace(
            float(np.min(finite_values)),
            float(np.max(finite_values)),
            7,
        )
        contours = axis.contour(
            source_inlet_values_C,
            high_stage_evaporation_values_C,
            masked_matrix,
            levels=contour_levels,
            colors="black",
            linewidths=0.65,
        )
        axis.clabel(contours, inline=True, fontsize=7.5, fmt="%.2f")

    colorbar = figure.colorbar(image, ax=axis)
    colorbar.set_label("Overall electrical COP [-]")
    axis.set_xlabel("Heat-source inlet temperature [°C]")
    axis.set_ylabel("High-stage evaporation temperature [°C]")
    axis.set_title(
        f"{title}\n"
        f"{settings.HEATING_CAPACITY_KW:g} kW | "
        f"Water {settings.INTEGRATED_WATER_MAIN_INLET_C:g}→"
        f"{settings.INTEGRATED_WATER_MAIN_OUTLET_C:g} °C at "
        f"{settings.INTEGRATED_WATER_PRESSURE_BAR:g} bar"
    )
    axis.set_xlim(
        float(np.min(source_inlet_values_C)),
        float(np.max(source_inlet_values_C)),
    )
    axis.set_ylim(
        float(np.min(high_stage_evaporation_values_C)),
        float(np.max(high_stage_evaporation_values_C)),
    )
    finish_axis(axis)
    save_standard_figure(figure, path, settings.FIGURE_DPI)
    plt.close(figure)


def main() -> None:
    configure_plot_style()
    RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    source_inlet_values_C = np.linspace(
        MAP_SOURCE_INLET_MIN_C,
        MAP_SOURCE_INLET_MAX_C,
        MAP_SOURCE_INLET_POINTS,
    )
    high_stage_evaporation_values_C = np.linspace(
        settings.INTEGRATED_HIGH_EVAPORATION_MIN_C,
        settings.INTEGRATED_HIGH_EVAPORATION_MAX_C,
        MAP_HIGH_EVAPORATION_POINTS,
    )
    matrices, records = calculate_cop_maps(
        source_inlet_values_C,
        high_stage_evaporation_values_C,
    )
    maximum_matrix, maximum_records = maximum_cop_envelope(
        source_inlet_values_C,
        high_stage_evaporation_values_C,
        matrices,
    )
    save_csv(
        records,
        RESULTS_DIRECTORY / "heat_source_evaporation_COP_map.csv",
    )
    save_csv(
        maximum_records,
        RESULTS_DIRECTORY / "maximum_COP_envelope.csv",
    )

    valid_arrays = [
        matrix[np.isfinite(matrix)]
        for matrix in matrices.values()
        if np.isfinite(matrix).any()
    ]
    if not valid_arrays:
        raise ValueError("Nenhum ponto válido foi encontrado para os mapas.")
    all_valid_values = np.concatenate(valid_arrays)
    common_minimum = float(np.min(all_valid_values))
    common_maximum = float(np.max(all_valid_values))

    for index, (architecture, _, _) in enumerate(
        ALL_TECHNOLOGY_ARCHITECTURES,
        start=1,
    ):
        _save_map(
            source_inlet_values_C,
            high_stage_evaporation_values_C,
            matrices[architecture],
            title=f"Integrated cascade COP — {architecture}",
            path=(
                RESULTS_DIRECTORY
                / f"{index:02d}_{_filename_slug(architecture)}_COP_map"
            ),
            common_minimum=common_minimum,
            common_maximum=common_maximum,
        )
    _save_map(
        source_inlet_values_C,
        high_stage_evaporation_values_C,
        maximum_matrix,
        title="Maximum COP among cascade configurations",
        path=RESULTS_DIRECTORY / "08_maximum_COP_among_configurations",
        common_minimum=common_minimum,
        common_maximum=common_maximum,
    )
    report_completion(
        "Mapa fonte térmica–evaporação do modelo integrado",
        records,
        RESULTS_DIRECTORY,
    )


if __name__ == "__main__":
    main()
