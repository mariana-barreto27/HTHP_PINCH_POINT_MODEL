"""Executa o modelo de pinch point integrado para vapor e água quente."""

from __future__ import annotations

from pathlib import Path

from analysis import settings
from analysis.common import configure_plot_style, save_csv
from analysis.plot_style import COLORS, DASHES, finish_axis, save_standard_figure

import matplotlib.pyplot as plt

from hthp.components.external_subcooler import ExternalSubcoolerConfig
from hthp.components.compressor_performance import (
    CompressorHardwareConfig,
    LinearPressureRatioEfficiency,
    QuadraticPressureRatioEfficiency,
)
from hthp.cycles.integrated_pinch_cascade import (
    IntegratedPinchCascadeConfig,
    IntegratedPinchCascadeCycle,
    IntegratedPinchCascadeResult,
)
from hthp.heat_sinks.hot_water import HotWaterHeatSink
from hthp.heat_sinks.steam import SteamHeatSink
from hthp.heat_sources.pinch_stream import PinchStreamHeatSource
from hthp.pinch import PinchPointConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIRECTORY = PROJECT_ROOT / "results_pinch_point"
MODE_LABELS = {
    "steam": (
        f"Saturated steam at {settings.INTEGRATED_STEAM_TARGET_C:g} °C"
    ),
    "hot_water": (
        f"{settings.INTEGRATED_WATER_MAIN_INLET_C:g}→"
        f"{settings.INTEGRATED_WATER_MAIN_OUTLET_C:g} °C at "
        f"{settings.INTEGRATED_WATER_PRESSURE_BAR:g} bar"
    ),
}
MODE_PLOT_CONDITIONS = {
    "steam": f"{settings.HEATING_CAPACITY_KW:g} kW",
    "hot_water": (
        f"{settings.HEATING_CAPACITY_KW:g} kW | "
        f"{settings.INTEGRATED_WATER_MAIN_INLET_C:g}→"
        f"{settings.INTEGRATED_WATER_MAIN_OUTLET_C:g} °C | "
        f"{settings.INTEGRATED_WATER_PRESSURE_BAR:g} bar"
    ),
}
MODE_CONDITIONS = {
    "steam": (
        f"Feedwater at {settings.INTEGRATED_STEAM_FEEDWATER_C:g} °C; "
        f"saturated steam at {settings.INTEGRATED_STEAM_TARGET_C:g} °C; "
        f"quality = {settings.INTEGRATED_STEAM_QUALITY:g}"
    ),
    "hot_water": (
        f"Main water stream from {settings.INTEGRATED_WATER_MAIN_INLET_C:g} "
        f"to {settings.INTEGRATED_WATER_MAIN_OUTLET_C:g} °C at "
        f"{settings.INTEGRATED_WATER_PRESSURE_BAR:g} bar; "
        f"{settings.INTEGRATED_WATER_MAKEUP_MASS_FLOW_KG_H:g} kg/h makeup "
        f"water at {settings.INTEGRATED_WATER_MAKEUP_INLET_C:g} °C, "
        "preheated in the subcooler and mixed before the condenser"
    ),
}
ARCHITECTURES = [
    ("Conventional cascade + subcooler", "simple", "simple"),
    (
        "Low-stage flash tank + subcooler",
        "flash_tank",
        "simple",
    ),
    (
        "High-stage flash tank + subcooler",
        "simple",
        "flash_tank",
    ),
    (
        "Flash tanks in both stages + subcooler",
        "flash_tank",
        "flash_tank",
    ),
]


def _build_heat_sink(mode: str) -> SteamHeatSink | HotWaterHeatSink:
    if mode == "steam":
        return SteamHeatSink(
            target_temperature_C=settings.INTEGRATED_STEAM_TARGET_C,
            feedwater_temperature_C=settings.INTEGRATED_STEAM_FEEDWATER_C,
            outlet_quality=settings.INTEGRATED_STEAM_QUALITY,
        )
    if mode == "hot_water":
        return HotWaterHeatSink(
            main_inlet_temperature_C=(
                settings.INTEGRATED_WATER_MAIN_INLET_C
            ),
            main_outlet_temperature_C=(
                settings.INTEGRATED_WATER_MAIN_OUTLET_C
            ),
            pressure_bar=settings.INTEGRATED_WATER_PRESSURE_BAR,
            makeup_inlet_temperature_C=(
                settings.INTEGRATED_WATER_MAKEUP_INLET_C
            ),
            makeup_mass_flow_kg_s=(
                settings.INTEGRATED_WATER_MAKEUP_MASS_FLOW_KG_H / 3600.0
            ),
        )
    raise ValueError(f"Modo de consumidor desconhecido: {mode}.")


def build_integrated_config(
    mode: str,
    low_stage_technology: str = "simple",
    high_stage_technology: str = "simple",
    compressor_efficiency_mode: str | None = None,
    external_subcooler_effectiveness: float | None = None,
) -> IntegratedPinchCascadeConfig:
    """Concentra em um lugar as hipóteses do modelo integrado."""
    if compressor_efficiency_mode is None:
        compressor_efficiency_mode = (
            "linear"
            if settings.INTEGRATED_USE_LINEAR_COMPRESSOR_EFFICIENCY
            else "constant"
        )
    low_efficiency_model = None
    high_efficiency_model = None
    if compressor_efficiency_mode == "linear":
        low_efficiency_model = LinearPressureRatioEfficiency(
            efficiency_at_unit_pressure_ratio=(
                settings.INTEGRATED_COMPRESSOR_EFFICIENCY_AT_UNIT_PRESSURE_RATIO
            ),
            slope_per_pressure_ratio=(
                settings.INTEGRATED_COMPRESSOR_EFFICIENCY_SLOPE_PER_PRESSURE_RATIO
            ),
            minimum_efficiency=(
                settings.INTEGRATED_COMPRESSOR_EFFICIENCY_MIN
            ),
            maximum_efficiency=(
                settings.INTEGRATED_COMPRESSOR_EFFICIENCY_MAX
            ),
        )
        high_efficiency_model = LinearPressureRatioEfficiency(
            efficiency_at_unit_pressure_ratio=(
                settings.INTEGRATED_COMPRESSOR_EFFICIENCY_AT_UNIT_PRESSURE_RATIO
            ),
            slope_per_pressure_ratio=(
                settings.INTEGRATED_COMPRESSOR_EFFICIENCY_SLOPE_PER_PRESSURE_RATIO
            ),
            minimum_efficiency=(
                settings.INTEGRATED_COMPRESSOR_EFFICIENCY_MIN
            ),
            maximum_efficiency=(
                settings.INTEGRATED_COMPRESSOR_EFFICIENCY_MAX
            ),
        )
    elif compressor_efficiency_mode == "reference_quadratic":
        low_efficiency_model = QuadraticPressureRatioEfficiency(
            *settings.INTEGRATED_LOW_COMPRESSOR_EFFICIENCY_COEFFICIENTS,
            minimum_efficiency=(
                settings.INTEGRATED_COMPRESSOR_EFFICIENCY_MIN
            ),
            maximum_efficiency=(
                settings.INTEGRATED_COMPRESSOR_EFFICIENCY_MAX
            ),
        )
        high_efficiency_model = QuadraticPressureRatioEfficiency(
            *settings.INTEGRATED_HIGH_COMPRESSOR_EFFICIENCY_COEFFICIENTS,
            minimum_efficiency=(
                settings.INTEGRATED_COMPRESSOR_EFFICIENCY_MIN
            ),
            maximum_efficiency=(
                settings.INTEGRATED_COMPRESSOR_EFFICIENCY_MAX
            ),
        )
    elif compressor_efficiency_mode != "constant":
        raise ValueError(
            "Modelo de eficiência do compressor desconhecido: "
            f"{compressor_efficiency_mode}."
        )
    if external_subcooler_effectiveness is None:
        external_subcooler_effectiveness = (
            settings.INTEGRATED_EXTERNAL_SUBCOOLER_EFFECTIVENESS
        )
    return IntegratedPinchCascadeConfig(
        external_heat_source=PinchStreamHeatSource(
            inlet_temperature_C=settings.INTEGRATED_SOURCE_INLET_C,
            outlet_temperature_C=settings.INTEGRATED_SOURCE_OUTLET_C,
            evaporator_pinch_K=settings.INTEGRATED_PINCH_EVAPORATOR_K,
            pressure_bar=settings.INTEGRATED_SOURCE_PRESSURE_BAR,
            fluid=settings.INTEGRATED_SOURCE_FLUID,
        ),
        heat_sink=_build_heat_sink(mode),
        pinch_points=PinchPointConfig(
            evaporator_K=settings.INTEGRATED_PINCH_EVAPORATOR_K,
            condenser_K=settings.INTEGRATED_PINCH_CONDENSER_K,
            cascade_K=settings.INTEGRATED_PINCH_CASCADE_K,
        ),
        external_subcooler=ExternalSubcoolerConfig(
            effectiveness=external_subcooler_effectiveness,
        ),
        economizer_effectiveness=(
            settings.INTEGRATED_ECONOMIZER_EFFECTIVENESS
        ),
        economizer_minimum_approach_K=(
            settings.INTEGRATED_ECONOMIZER_MINIMUM_APPROACH_K
        ),
        low_stage_compressor_hardware=CompressorHardwareConfig(
            mode="required_speed",
            clearance_fraction=(
                settings.INTEGRATED_LOW_COMPRESSOR_CLEARANCE
            ),
            fixed_displacement_m3_rev=(
                settings.INTEGRATED_LOW_COMPRESSOR_DISPLACEMENT_M3_REV
            ),
            minimum_speed_Hz=(
                settings.INTEGRATED_LOW_COMPRESSOR_MINIMUM_SPEED_HZ
            ),
            maximum_speed_Hz=(
                settings.INTEGRATED_LOW_COMPRESSOR_MAXIMUM_SPEED_HZ
            ),
        ),
        high_stage_compressor_hardware=CompressorHardwareConfig(
            mode="size_displacement",
            clearance_fraction=(
                settings.INTEGRATED_HIGH_COMPRESSOR_CLEARANCE
            ),
            fixed_speed_Hz=(
                settings.INTEGRATED_HIGH_COMPRESSOR_FIXED_SPEED_HZ
            ),
        ),
        enforce_compressor_speed_limits=(
            settings.INTEGRATED_ENFORCE_COMPRESSOR_SPEED_LIMITS
        ),
        heating_capacity_kW=settings.HEATING_CAPACITY_KW,
        low_stage_refrigerant=settings.CASCADE_LOW_STAGE_REFRIGERANT,
        high_stage_refrigerant=settings.CASCADE_HIGH_STAGE_REFRIGERANT,
        low_stage_technology=low_stage_technology,
        high_stage_technology=high_stage_technology,
        superheat_K=settings.SUPERHEAT_K,
        subcooling_K=settings.SUBCOOLING_K,
        compressor_isentropic_efficiency=(
            settings.COMPRESSOR_ISENTROPIC_EFFICIENCY
        ),
        motor_efficiency=settings.MOTOR_EFFICIENCY,
        low_stage_compressor_efficiency_model=low_efficiency_model,
        high_stage_compressor_efficiency_model=high_efficiency_model,
        reject_limited_compressor_efficiencies=(
            settings.INTEGRATED_REJECT_COMPRESSOR_EFFICIENCY_LIMITS
        ),
        optimization_high_stage_evaporation_minimum_C=(
            settings.INTEGRATED_HIGH_EVAPORATION_MIN_C
        ),
        optimization_high_stage_evaporation_maximum_C=(
            settings.INTEGRATED_HIGH_EVAPORATION_MAX_C
        ),
        optimization_step_K=settings.INTEGRATED_HIGH_EVAPORATION_STEP_K,
        optimization_tolerance_K=(
            settings.INTEGRATED_TEMPERATURE_OPTIMIZATION_TOLERANCE_K
        ),
        optimization_maximum_iterations=(
            settings.INTEGRATED_TEMPERATURE_OPTIMIZATION_MAX_ITERATIONS
        ),
        flash_optimization_points=(
            settings.INTEGRATED_FLASH_OPTIMIZATION_POINTS
        ),
        flash_refinement_iterations=(
            settings.INTEGRATED_FLASH_REFINEMENT_ITERATIONS
        ),
    )


def result_record(
    mode: str,
    result: IntegratedPinchCascadeResult,
    is_optimum: bool,
    architecture: str = "Conventional cascade",
) -> dict[str, float | bool | str]:
    """Converte um resultado completo em uma linha legível de CSV."""
    return {
        "sink_mode": mode,
        "sink_label": MODE_LABELS[mode],
        "sink_condition": MODE_CONDITIONS[mode],
        "architecture": architecture,
        "is_optimum": is_optimum,
        "low_stage_technology": result.config.low_stage_technology,
        "high_stage_technology": result.config.high_stage_technology,
        "low_stage_refrigerant": result.config.low_stage_refrigerant,
        "high_stage_refrigerant": result.config.high_stage_refrigerant,
        "source_inlet_temperature_C": (
            result.config.external_heat_source.inlet_temperature_C
        ),
        "source_outlet_temperature_C": (
            result.config.external_heat_source.outlet_temperature_C
        ),
        "low_stage_evaporation_temperature_C": (
            result.low_stage.evaporation_temperature_C
        ),
        "low_stage_condensation_temperature_C": (
            result.low_stage_condensation_temperature_C
        ),
        "high_stage_evaporation_temperature_C": (
            result.high_stage_evaporation_temperature_C
        ),
        "high_stage_condensation_temperature_C": (
            result.high_stage.condensation_temperature_C
        ),
        "evaporator_pinch_K": result.config.pinch_points.evaporator_K,
        "cascade_pinch_K": result.config.pinch_points.cascade_K,
        "condenser_pinch_K": result.config.pinch_points.condenser_K,
        "superheat_K": result.config.superheat_K,
        "subcooling_K": result.config.subcooling_K,
        "total_useful_heat_kW": result.high_stage.total_useful_heat_kW,
        "main_condenser_heat_kW": result.high_stage.main_condenser_heat_kW,
        "external_subcooler_heat_kW": (
            result.high_stage.external_subcooler_heat_kW
        ),
        "external_subcooler_effectiveness": (
            result.config.external_subcooler.effectiveness
        ),
        "external_subcooler_location": (
            "refrigerant side, after main condenser"
        ),
        "compressor_efficiency_model": (
            type(result.config.low_stage_compressor_efficiency_model).__name__
            if result.config.low_stage_compressor_efficiency_model is not None
            else "constant"
        ),
        "compressor_efficiency_limit_policy": (
            "reject_limited_points"
            if result.config.reject_limited_compressor_efficiencies
            else "clip_to_limits"
        ),
        "low_stage_compressor_isentropic_efficiencies": "|".join(
            f"{value:.8f}"
            for value in result.low_stage.compressor_isentropic_efficiencies
        ),
        "low_stage_compressor_raw_isentropic_efficiencies": "|".join(
            f"{value:.8f}"
            for value in (
                result.low_stage.compressor_raw_isentropic_efficiencies
            )
        ),
        "low_stage_compressor_efficiency_limit_statuses": "|".join(
            result.low_stage.compressor_efficiency_limit_statuses
        ),
        "high_stage_compressor_isentropic_efficiencies": "|".join(
            f"{value:.8f}"
            for value in result.high_stage.compressor_isentropic_efficiencies
        ),
        "high_stage_compressor_raw_isentropic_efficiencies": "|".join(
            f"{value:.8f}"
            for value in (
                result.high_stage.stage.compressor_raw_isentropic_efficiencies
            )
        ),
        "high_stage_compressor_efficiency_limit_statuses": "|".join(
            result.high_stage.stage.compressor_efficiency_limit_statuses
        ),
        "any_compressor_efficiency_limit_active": any(
            status != "none"
            for status in (
                result.low_stage.compressor_efficiency_limit_statuses
                + result.high_stage.stage.compressor_efficiency_limit_statuses
            )
        ),
        "low_stage_compressor_required_speeds_rpm": "|".join(
            f"{compressor.required_speed_rpm:.4f}"
            for compressor in result.low_stage_compressors
        ),
        "low_stage_compressor_pressure_ratios": "|".join(
            f"{compressor.pressure_ratio:.8f}"
            for compressor in result.low_stage_compressors
        ),
        "low_stage_compressor_volumetric_efficiencies": "|".join(
            f"{compressor.volumetric_efficiency:.8f}"
            for compressor in result.low_stage_compressors
        ),
        "low_stage_compressor_speeds_feasible": all(
            compressor.speed_feasible
            for compressor in result.low_stage_compressors
        ),
        "high_stage_required_displacements_m3_rev": "|".join(
            f"{compressor.required_displacement_m3_rev:.10f}"
            for compressor in result.high_stage_compressors
        ),
        "high_stage_compressor_pressure_ratios": "|".join(
            f"{compressor.pressure_ratio:.8f}"
            for compressor in result.high_stage_compressors
        ),
        "high_stage_required_displacements_cm3_rev": "|".join(
            f"{compressor.required_displacement_m3_rev * 1.0e6:.4f}"
            for compressor in result.high_stage_compressors
        ),
        "high_stage_compressor_volumetric_efficiencies": "|".join(
            f"{compressor.volumetric_efficiency:.8f}"
            for compressor in result.high_stage_compressors
        ),
        "flash_compressor_hardware_assumption": (
            "same stage hardware specification applied independently"
        ),
        "low_stage_intermediate_pressure_bar": (
            ""
            if result.low_stage.intermediate_pressure_bar is None
            else result.low_stage.intermediate_pressure_bar
        ),
        "high_stage_intermediate_pressure_bar": (
            ""
            if result.high_stage.intermediate_pressure_bar is None
            else result.high_stage.intermediate_pressure_bar
        ),
        "low_stage_economizer_injection_mass_fraction": (
            ""
            if result.low_stage.injection_mass_fraction is None
            else result.low_stage.injection_mass_fraction
        ),
        "high_stage_economizer_injection_mass_fraction": (
            ""
            if result.high_stage.stage.injection_mass_fraction is None
            else result.high_stage.stage.injection_mass_fraction
        ),
        "low_stage_economizer_heat_kW": result.low_stage.economizer_heat_kW,
        "high_stage_economizer_heat_kW": (
            result.high_stage.stage.economizer_heat_kW
        ),
        "total_electrical_power_kW": result.total_electrical_power_kW,
        "overall_COP_electrical": result.overall_COP_electrical,
        "source_mass_flow_kg_s": result.source_mass_flow_kg_s,
        "final_sink_temperature_C": result.heat_sink.final_outlet_temperature_C,
        "final_sink_mass_flow_kg_s": result.heat_sink.final_stream_mass_flow_kg_s,
        "final_sink_quality": (
            ""
            if result.heat_sink.final_outlet_quality is None
            else result.heat_sink.final_outlet_quality
        ),
        "UA_high_stage_condenser_kW_K": (
            result.heat_exchangers["high_stage_condenser"].ua_kW_K
        ),
        "UA_external_subcooler_kW_K": (
            result.heat_exchangers["external_subcooler"].ua_kW_K
        ),
        "UA_cascade_kW_K": result.heat_exchangers["cascade"].ua_kW_K,
        "UA_low_stage_evaporator_kW_K": (
            result.heat_exchangers["low_stage_evaporator"].ua_kW_K
        ),
        "interstage_balance_error_kW": (
            result.interstage_heat_balance_error_kW
        ),
        "overall_balance_error_kW": result.overall_energy_balance_error_kW,
        "sink_balance_error_kW": result.heat_sink.energy_balance_error_kW,
    }


def write_architecture_optimum_latex(
    rows: list[dict[str, float | bool | str]],
    output_path: Path,
) -> None:
    """Grava uma tabela LaTeX com os ótimos das arquiteturas ativas."""

    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        (
            r"\caption{Optimal high-stage evaporation temperature and "
            r"maximum COP for the integrated pinch-point model.}"
        ),
        r"\label{tab:integrated_pinch_optimum}",
        r"\small",
        r"\begin{tabular}{lrrrrr}",
        r"\hline",
        (
            r"\textbf{Configuration} & "
            r"\textbf{$T_{\mathrm{evap,high}}^{*}$} & "
            r"\textbf{$Q_{cond}$} & \textbf{$Q_{SC}$} & "
            r"\textbf{$W_{el}$} & \textbf{$COP_{el}^{*}$} \\"
        ),
        (
            r" & \textbf{[$^{\circ}$C]} & \textbf{[kW]} & "
            r"\textbf{[kW]} & \textbf{[kW]} & \\"
        ),
        r"\hline",
    ]
    for mode in settings.INTEGRATED_PINCH_SINK_MODES:
        mode_rows = [row for row in rows if row["sink_mode"] == mode]
        if not mode_rows:
            continue
        if mode == "hot_water":
            condition = (
                r"Water: "
                f"{settings.INTEGRATED_WATER_MAIN_INLET_C:g}"
                r"$\rightarrow$"
                f"{settings.INTEGRATED_WATER_MAIN_OUTLET_C:g} "
                r"$^{\circ}$C at "
                f"{settings.INTEGRATED_WATER_PRESSURE_BAR:g} bar"
            )
        else:
            condition = (
                "Saturated steam at "
                f"{settings.INTEGRATED_STEAM_TARGET_C:g} "
                r"$^{\circ}$C"
            )
        lines.extend(
            [
                rf"\multicolumn{{6}}{{c}}{{\textit{{{condition}}}}} \\",
                r"\hline",
            ]
        )
        for row in mode_rows:
            lines.append(
                f"{row['architecture']} & "
                f"{float(row['high_stage_evaporation_temperature_C']):.1f}"
                " & "
                f"{float(row['main_condenser_heat_kW']):.2f} & "
                f"{float(row['external_subcooler_heat_kW']):.2f} & "
                f"{float(row['total_electrical_power_kW']):.2f} & "
                f"{float(row['overall_COP_electrical']):.3f} \\\\"
            )
        lines.append(r"\hline")
    lines.extend(
        [
            r"\end{tabular}",
            "",
            r"\vspace{1.5mm}",
            r"\begin{minipage}{0.96\linewidth}",
            r"\footnotesize",
            (
                f"Heating duty: {settings.HEATING_CAPACITY_KW:g} kW. "
                "Low-stage refrigerant: "
                f"{settings.CASCADE_LOW_STAGE_REFRIGERANT}; "
                "high-stage refrigerant: "
                f"{settings.CASCADE_HIGH_STAGE_REFRIGERANT}."
            ),
            (
                "Evaporator, cascade and condenser pinch points: "
                f"{settings.INTEGRATED_PINCH_EVAPORATOR_K:g}, "
                f"{settings.INTEGRATED_PINCH_CASCADE_K:g} and "
                f"{settings.INTEGRATED_PINCH_CONDENSER_K:g} K. "
                f"Superheat and subcooling: {settings.SUPERHEAT_K:g} K."
            ),
            (
                "Linear compressor-efficiency model. No IHX is used. "
                "Maximum COP values are restricted to the evaluated "
                f"{settings.INTEGRATED_HIGH_EVAPORATION_MIN_C:g}--"
                f"{settings.INTEGRATED_HIGH_EVAPORATION_MAX_C:g} "
                r"$^{\circ}$C range."
            ),
            r"\end{minipage}",
            r"\end{table}",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _compact_optimum_rows(
    rows: list[dict[str, float | bool | str]],
) -> list[dict[str, float | str]]:
    """Seleciona somente os resultados de compressor pedidos para a tabela."""

    compact_rows: list[dict[str, float | str]] = []
    for row in rows:
        compact_rows.append(
            {
                "configuration": str(row["architecture"]),
                "optimal_high_stage_evaporation_temperature_C": float(
                    row["high_stage_evaporation_temperature_C"]
                ),
                "maximum_overall_COP": float(row["overall_COP_electrical"]),
                "low_stage_flash_pressure_bar": row[
                    "low_stage_intermediate_pressure_bar"
                ],
                "high_stage_flash_pressure_bar": row[
                    "high_stage_intermediate_pressure_bar"
                ],
                "low_stage_compressor_pressure_ratios": str(
                    row["low_stage_compressor_pressure_ratios"]
                ),
                "low_stage_compressor_isentropic_efficiencies": str(
                    row["low_stage_compressor_isentropic_efficiencies"]
                ),
                "high_stage_compressor_pressure_ratios": str(
                    row["high_stage_compressor_pressure_ratios"]
                ),
                "high_stage_compressor_isentropic_efficiencies": str(
                    row["high_stage_compressor_isentropic_efficiencies"]
                ),
            }
        )
    return compact_rows


def _format_sequence_for_latex(value: object) -> str:
    """Formata um ou dois valores de compressor na mesma célula."""

    text = str(value).strip()
    if not text:
        return "--"
    return " / ".join(f"{float(item):.3f}" for item in text.split("|"))


def _format_flash_pressure_for_latex(value: object) -> str:
    """Mostra a pressão de flash ou um traço quando ela não se aplica."""

    if value == "" or value is None:
        return "--"
    return f"{float(value):.2f}"


def write_compressor_optimum_latex(
    rows: list[dict[str, float | bool | str]],
    output_path: Path,
) -> None:
    """Grava a tabela compacta do ponto ótimo dos compressores."""

    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        (
            r"\caption{Optimal compressor conditions for the integrated "
            r"pinch-point cascade.}"
        ),
        r"\label{tab:integrated_pinch_compressor_optimum}",
        r"\scriptsize",
        r"\setlength{\tabcolsep}{3pt}",
        r"\begin{tabular}{lrrrrrrrr}",
        r"\hline",
        (
            r"\textbf{Configuration} & "
            r"\textbf{$T_{ev,h}^{*}$} & \textbf{$COP^{*}$} & "
            r"\textbf{$P_{fl,l}$} & \textbf{$P_{fl,h}$} & "
            r"\textbf{$RP_l$} & \textbf{$\eta_{is,l}$} & "
            r"\textbf{$RP_h$} & \textbf{$\eta_{is,h}$} \\"
        ),
        (
            r" & \textbf{[$^{\circ}$C]} & & \textbf{[bar]} & "
            r"\textbf{[bar]} & & & & \\"
        ),
        r"\hline",
    ]
    for row in rows:
        lines.append(
            f"{row['architecture']} & "
            f"{float(row['high_stage_evaporation_temperature_C']):.1f} & "
            f"{float(row['overall_COP_electrical']):.3f} & "
            f"{_format_flash_pressure_for_latex(row['low_stage_intermediate_pressure_bar'])} & "
            f"{_format_flash_pressure_for_latex(row['high_stage_intermediate_pressure_bar'])} & "
            f"{_format_sequence_for_latex(row['low_stage_compressor_pressure_ratios'])} & "
            f"{_format_sequence_for_latex(row['low_stage_compressor_isentropic_efficiencies'])} & "
            f"{_format_sequence_for_latex(row['high_stage_compressor_pressure_ratios'])} & "
            f"{_format_sequence_for_latex(row['high_stage_compressor_isentropic_efficiencies'])}"
            + r" \\"
        )
    lines.extend(
        [
            r"\hline",
            r"\end{tabular}",
            r"\end{table}",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    configure_plot_style()
    RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, float | bool | str]] = []
    curves: list[tuple[str, list[dict[str, float | bool | str]]]] = []
    optimizations = {}

    for mode in settings.INTEGRATED_PINCH_SINK_MODES:
        solver = IntegratedPinchCascadeCycle(build_integrated_config(mode))
        optimization = solver.optimize_intermediate_temperature()
        optimizations[(mode, "simple", "simple")] = optimization
        optimum = optimization.optimum
        rows = [
            result_record(
                mode,
                result,
                result is optimum,
            )
            for result in optimization.valid_points
        ]
        save_csv(rows, RESULTS_DIRECTORY / f"{mode}_temperature_sweep.csv")
        optimum_row = result_record(mode, optimum, True)
        optimum_row.update(
            {
                "valid_optimization_points": len(optimization.valid_points),
                "invalid_optimization_points": optimization.invalid_point_count,
                "optimum_at_boundary": (
                    optimization.optimum_at_temperature_boundary
                ),
                "optimization_method": optimization.optimization_method,
                "function_evaluations": optimization.function_evaluations,
                "temperature_optimization_tolerance_K": (
                    settings.INTEGRATED_TEMPERATURE_OPTIMIZATION_TOLERANCE_K
                ),
            }
        )
        summary.append(optimum_row)
        curves.append((mode, rows))

    save_csv(summary, RESULTS_DIRECTORY / "optimum_summary.csv")

    figure, axis = plt.subplots()
    for index, (mode, rows) in enumerate(curves):
        x_values = [
            float(row["high_stage_evaporation_temperature_C"])
            for row in rows
        ]
        y_values = [float(row["overall_COP_electrical"]) for row in rows]
        axis.plot(
            x_values,
            y_values,
            color=COLORS[index],
            linestyle=DASHES[index],
            marker="none",
            label=MODE_LABELS[mode],
        )
    axis.set_xlabel("High-stage evaporation temperature [°C]")
    axis.set_ylabel("Overall COP [-]")
    active_conditions = " | ".join(
        MODE_LABELS[mode] for mode in settings.INTEGRATED_PINCH_SINK_MODES
    )
    axis.set_title(
        "Integrated pinch-point cascade\n"
        f"{settings.HEATING_CAPACITY_KW:g} kW | {active_conditions}"
    )
    finish_axis(axis)
    axis.legend()
    save_standard_figure(
        figure,
        RESULTS_DIRECTORY / "01_COP_vs_high_stage_evaporation_temperature",
        settings.FIGURE_DPI,
    )
    plt.close(figure)

    architecture_summary: list[dict[str, float | bool | str]] = []
    for figure_number, mode in enumerate(
        settings.INTEGRATED_PINCH_SINK_MODES,
        start=2,
    ):
        architecture_curves: list[
            tuple[str, list[dict[str, float | bool | str]]]
        ] = []
        all_mode_rows: list[dict[str, float | bool | str]] = []
        for architecture, low_technology, high_technology in ARCHITECTURES:
            key = (mode, low_technology, high_technology)
            optimization = optimizations.get(key)
            if optimization is None:
                optimization = IntegratedPinchCascadeCycle(
                    build_integrated_config(
                        mode,
                        low_technology,
                        high_technology,
                    )
                ).optimize_intermediate_temperature()
                optimizations[key] = optimization
            optimum = optimization.optimum
            rows = [
                result_record(
                    mode,
                    result,
                    result is optimum,
                    architecture,
                )
                for result in optimization.valid_points
            ]
            all_mode_rows.extend(rows)
            architecture_curves.append((architecture, rows))
            optimum_row = result_record(
                mode,
                optimum,
                True,
                architecture,
            )
            optimum_row.update(
                {
                    "valid_optimization_points": len(
                        optimization.valid_points
                    ),
                    "invalid_optimization_points": (
                        optimization.invalid_point_count
                    ),
                    "optimum_at_boundary": (
                        optimization.optimum_at_temperature_boundary
                    ),
                    "optimization_method": optimization.optimization_method,
                    "function_evaluations": optimization.function_evaluations,
                    "temperature_optimization_tolerance_K": (
                        settings.INTEGRATED_TEMPERATURE_OPTIMIZATION_TOLERANCE_K
                    ),
                }
            )
            architecture_summary.append(optimum_row)
        save_csv(
            all_mode_rows,
            RESULTS_DIRECTORY / f"{mode}_architecture_temperature_sweep.csv",
        )

        figure, axis = plt.subplots()
        for index, (architecture, rows) in enumerate(architecture_curves):
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
        title = (
            f"Integrated cascade — {MODE_LABELS[mode]}"
            if mode == "steam"
            else "Integrated cascade"
        )
        axis.set_title(f"{title}\n{MODE_PLOT_CONDITIONS[mode]}")
        finish_axis(axis)
        axis.legend(ncol=2, fontsize=7)
        save_standard_figure(
            figure,
            RESULTS_DIRECTORY
            / f"{figure_number:02d}_{mode}_architecture_comparison",
            settings.FIGURE_DPI,
        )
        plt.close(figure)

    save_csv(
        architecture_summary,
        RESULTS_DIRECTORY / "architecture_optimum_summary.csv",
    )
    write_architecture_optimum_latex(
        architecture_summary,
        RESULTS_DIRECTORY / "architecture_optimum_table.tex",
    )
    compact_rows = _compact_optimum_rows(architecture_summary)
    save_csv(
        compact_rows,
        RESULTS_DIRECTORY / "compressor_optimum_table.csv",
    )
    write_compressor_optimum_latex(
        architecture_summary,
        RESULTS_DIRECTORY / "compressor_optimum_table.tex",
    )

    print(f"Integrated pinch-point model: results in {RESULTS_DIRECTORY}")


if __name__ == "__main__":
    main()
