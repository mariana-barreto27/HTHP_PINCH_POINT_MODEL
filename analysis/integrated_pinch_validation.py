"""Valida o ponto-base do modelo integrado de água quente."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

from analysis import settings
from analysis.common import save_csv
from analysis.integrated_pinch_model import (
    ARCHITECTURES,
    build_integrated_config,
)

from hthp.cycles.integrated_pinch_cascade import (
    IntegratedPinchCascadeCycle,
    IntegratedPinchCascadeResult,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIRECTORY = PROJECT_ROOT / "results_pinch_point" / "validation"

BALANCE_TOLERANCE_KW = 1.0e-6
TEMPERATURE_TOLERANCE_K = 1.0e-6
REFERENCE_RELATIVE_TOLERANCE = 1.0e-9
REFERENCE_ABSOLUTE_TOLERANCE = 1.0e-9

# Valores obtidos diretamente do arquivo Pinch_point_model.py fornecido pelo
# orientador, no ponto T_evap,alta=35 °C e com a correlação quadrática original.
# O COP desse arquivo é baseado na potência de eixo, sem a eficiência do motor.
JULIO_BASE_POINT = {
    "high_stage_evaporation_temperature_C": 35.0,
    "low_stage_condensation_temperature_C": 45.0,
    "main_condenser_heat_kW": 101.13702250701283,
    "subcooler_heat_kW": 18.862977492987174,
    "total_useful_heat_kW": 120.0,
    "total_shaft_power_kW": 75.99413902816637,
    "overall_COP_shaft": 1.5790691431548867,
    "source_mass_flow_kg_s": 4.374427216064658,
}

REFERENCE_LABELS_AND_UNITS = {
    "high_stage_evaporation_temperature_C": (
        "High-stage evaporation temperature",
        "°C",
    ),
    "low_stage_condensation_temperature_C": (
        "Low-stage condensation temperature",
        "°C",
    ),
    "main_condenser_heat_kW": ("Main condenser duty", "kW"),
    "subcooler_heat_kW": ("Subcooler duty", "kW"),
    "total_useful_heat_kW": ("Total useful heat", "kW"),
    "total_shaft_power_kW": ("Total shaft power", "kW"),
    "overall_COP_shaft": ("Overall shaft COP", "-"),
    "source_mass_flow_kg_s": ("Heat-source mass flow", "kg/s"),
}


def _joined(values: tuple[float, ...], digits: int = 6) -> str:
    return "|".join(f"{value:.{digits}f}" for value in values)


def _status_join(values: tuple[str, ...]) -> str:
    return "|".join(values)


def _maximum_absolute(values: tuple[float, ...]) -> float:
    return max((abs(value) for value in values), default=0.0)


def validation_record(
    architecture: str,
    result: IntegratedPinchCascadeResult,
) -> dict[str, float | bool | str]:
    """Converte um resultado do ponto-base em registro auditável."""

    config = result.config
    sink = result.heat_sink
    low = result.low_stage
    high = result.high_stage

    duty_error = (
        high.main_condenser_heat_kW
        + high.external_subcooler_heat_kW
        - config.heating_capacity_kW
    )
    evaporator_pinch = (
        config.external_heat_source.outlet_temperature_C
        - low.evaporation_temperature_C
    )
    cascade_pinch = (
        result.low_stage_condensation_temperature_C
        - result.high_stage_evaporation_temperature_C
    )
    condenser_pinch = (
        high.condensation_temperature_C
        - sink.final_outlet_temperature_C
    )
    water_flow_error = (
        sink.final_stream_mass_flow_kg_s
        - sink.main_stream_mass_flow_kg_s
        - sink.subcooler_stream_mass_flow_kg_s
    )
    water_outlet_error = (
        sink.final_outlet_temperature_C
        - settings.INTEGRATED_WATER_MAIN_OUTLET_C
    )

    balance_pass = all(
        abs(value) <= BALANCE_TOLERANCE_KW
        for value in (
            duty_error,
            result.interstage_heat_balance_error_kW,
            result.overall_energy_balance_error_kW,
            sink.energy_balance_error_kW,
        )
    )
    pinch_pass = all(
        abs(actual - expected) <= TEMPERATURE_TOLERANCE_K
        for actual, expected in (
            (evaporator_pinch, config.pinch_points.evaporator_K),
            (cascade_pinch, config.pinch_points.cascade_K),
            (condenser_pinch, config.pinch_points.condenser_K),
        )
    )
    water_pass = (
        abs(water_flow_error) <= 1.0e-10
        and abs(water_outlet_error) <= TEMPERATURE_TOLERANCE_K
        and sink.main_inlet_temperature_C
        < sink.final_outlet_temperature_C
    )
    ua_pass = all(
        sizing.ua_kW_K > 0.0 and sizing.lmtd_K > 0.0
        for sizing in result.heat_exchangers.values()
    )
    speed_pass = all(
        compressor.speed_feasible
        for compressor in result.low_stage_compressors
    )
    cold_side_is_c_min = high.external_subcooler.cold_side_is_c_min
    core_pass = all(
        (
            balance_pass,
            pinch_pass,
            water_pass,
            ua_pass,
            speed_pass,
            cold_side_is_c_min,
            result.overall_COP_electrical > 1.0,
        )
    )
    limit_statuses = (
        low.compressor_efficiency_limit_statuses
        + high.stage.compressor_efficiency_limit_statuses
    )
    efficiency_limit_active = any(
        status != "none" for status in limit_statuses
    )
    if not core_pass:
        validation_status = "FAIL"
    elif efficiency_limit_active:
        validation_status = "PASS_WITH_WARNING"
    else:
        validation_status = "PASS"

    return {
        "architecture": architecture,
        "validation_status": validation_status,
        "balance_pass": balance_pass,
        "pinch_pass": pinch_pass,
        "water_balance_pass": water_pass,
        "positive_UA_pass": ua_pass,
        "compressor_speed_pass": speed_pass,
        "subcooler_cold_side_is_Cmin": cold_side_is_c_min,
        "compressor_efficiency_limit_active": efficiency_limit_active,
        "low_stage_technology": config.low_stage_technology,
        "high_stage_technology": config.high_stage_technology,
        "low_stage_refrigerant": config.low_stage_refrigerant,
        "high_stage_refrigerant": config.high_stage_refrigerant,
        "source_inlet_temperature_C": (
            config.external_heat_source.inlet_temperature_C
        ),
        "source_outlet_temperature_C": (
            config.external_heat_source.outlet_temperature_C
        ),
        "low_stage_evaporation_temperature_C": (
            low.evaporation_temperature_C
        ),
        "low_stage_condensation_temperature_C": (
            result.low_stage_condensation_temperature_C
        ),
        "high_stage_evaporation_temperature_C": (
            result.high_stage_evaporation_temperature_C
        ),
        "high_stage_condensation_temperature_C": (
            high.condensation_temperature_C
        ),
        "evaporator_pinch_K": evaporator_pinch,
        "cascade_pinch_K": cascade_pinch,
        "condenser_pinch_K": condenser_pinch,
        "main_condenser_heat_kW": high.main_condenser_heat_kW,
        "subcooler_heat_kW": high.external_subcooler_heat_kW,
        "total_useful_heat_kW": high.total_useful_heat_kW,
        "low_stage_evaporator_heat_kW": low.evaporator_heat_kW,
        "cascade_heat_kW": high.evaporator_heat_kW,
        "low_stage_shaft_power_kW": low.shaft_power_kW,
        "high_stage_shaft_power_kW": high.compressor_shaft_power_kW,
        "total_shaft_power_kW": result.total_shaft_power_kW,
        "total_electrical_power_kW": result.total_electrical_power_kW,
        "overall_COP_shaft": result.overall_COP_shaft,
        "overall_COP_electrical": result.overall_COP_electrical,
        "source_mass_flow_kg_s": result.source_mass_flow_kg_s,
        "low_stage_refrigerant_mass_flow_kg_s": (
            low.refrigerant_mass_flow_kg_s
        ),
        "high_stage_refrigerant_mass_flow_kg_s": (
            high.refrigerant_mass_flow_kg_s
        ),
        "water_makeup_inlet_temperature_C": (
            config.heat_sink.makeup_inlet_temperature_C
        ),
        "water_after_subcooler_temperature_C": (
            sink.subcooler_outlet_temperature_C
        ),
        "water_mixed_before_condenser_temperature_C": (
            sink.main_inlet_temperature_C
        ),
        "water_final_outlet_temperature_C": (
            sink.final_outlet_temperature_C
        ),
        "water_return_mass_flow_kg_s": sink.main_stream_mass_flow_kg_s,
        "water_makeup_mass_flow_kg_s": sink.subcooler_stream_mass_flow_kg_s,
        "water_final_mass_flow_kg_s": sink.final_stream_mass_flow_kg_s,
        "low_stage_pressure_ratios": _joined(
            tuple(item.pressure_ratio for item in result.low_stage_compressors)
        ),
        "high_stage_pressure_ratios": _joined(
            tuple(item.pressure_ratio for item in result.high_stage_compressors)
        ),
        "low_stage_isentropic_efficiencies": _joined(
            low.compressor_isentropic_efficiencies
        ),
        "high_stage_isentropic_efficiencies": _joined(
            high.compressor_isentropic_efficiencies
        ),
        "compressor_efficiency_limit_statuses": _status_join(limit_statuses),
        "low_stage_required_speeds_rpm": _joined(
            tuple(
                item.required_speed_rpm
                for item in result.low_stage_compressors
            ),
            digits=2,
        ),
        "high_stage_required_displacements_cm3_rev": _joined(
            tuple(
                item.required_displacement_m3_rev * 1.0e6
                for item in result.high_stage_compressors
            ),
            digits=2,
        ),
        "UA_high_stage_condenser_kW_K": (
            result.heat_exchangers["high_stage_condenser"].ua_kW_K
        ),
        "UA_subcooler_kW_K": (
            result.heat_exchangers["external_subcooler"].ua_kW_K
        ),
        "UA_cascade_kW_K": result.heat_exchangers["cascade"].ua_kW_K,
        "UA_low_stage_evaporator_kW_K": (
            result.heat_exchangers["low_stage_evaporator"].ua_kW_K
        ),
        "useful_heat_error_kW": duty_error,
        "interstage_balance_error_kW": (
            result.interstage_heat_balance_error_kW
        ),
        "overall_balance_error_kW": result.overall_energy_balance_error_kW,
        "water_sink_balance_error_kW": sink.energy_balance_error_kW,
        "maximum_absolute_balance_error_kW": _maximum_absolute(
            (
                duty_error,
                result.interstage_heat_balance_error_kW,
                result.overall_energy_balance_error_kW,
                sink.energy_balance_error_kW,
            )
        ),
    }


def solve_reference_architectures(
) -> list[dict[str, float | bool | str]]:
    """Resolve as quatro arquiteturas no mesmo ponto, sem otimizar temperatura."""

    high_evaporation_C = (
        settings.INTEGRATED_VALIDATION_HIGH_STAGE_EVAPORATION_C
    )
    low_condensation_C = (
        high_evaporation_C + settings.INTEGRATED_PINCH_CASCADE_K
    )
    rows = []
    for architecture, low_technology, high_technology in ARCHITECTURES:
        result = IntegratedPinchCascadeCycle(
            build_integrated_config(
                "hot_water",
                low_technology,
                high_technology,
                compressor_efficiency_mode="linear",
            )
        ).solve(low_condensation_C)
        rows.append(validation_record(architecture, result))
    return rows


def julio_regression_rows() -> list[dict[str, float | bool | str]]:
    """Compara o módulo atual com os números congelados do arquivo de origem."""

    # A regressão reproduz deliberadamente os 120 kW do arquivo original do
    # Júlio. Ela é independente da carga atual usada nas análises (170 kW).
    reference_config = replace(
        build_integrated_config(
            "hot_water",
            compressor_efficiency_mode="reference_quadratic",
        ),
        heating_capacity_kW=JULIO_BASE_POINT["total_useful_heat_kW"],
    )
    result = IntegratedPinchCascadeCycle(reference_config).solve(
        JULIO_BASE_POINT["low_stage_condensation_temperature_C"]
    )
    current = {
        "high_stage_evaporation_temperature_C": (
            result.high_stage_evaporation_temperature_C
        ),
        "low_stage_condensation_temperature_C": (
            result.low_stage_condensation_temperature_C
        ),
        "main_condenser_heat_kW": result.high_stage.main_condenser_heat_kW,
        "subcooler_heat_kW": result.high_stage.external_subcooler_heat_kW,
        "total_useful_heat_kW": result.high_stage.total_useful_heat_kW,
        "total_shaft_power_kW": result.total_shaft_power_kW,
        "overall_COP_shaft": result.overall_COP_shaft,
        "source_mass_flow_kg_s": result.source_mass_flow_kg_s,
    }
    rows: list[dict[str, float | bool | str]] = []
    for key, reference_value in JULIO_BASE_POINT.items():
        current_value = current[key]
        absolute_difference = current_value - reference_value
        relative_difference = (
            absolute_difference / reference_value
            if reference_value != 0.0
            else absolute_difference
        )
        match = math.isclose(
            current_value,
            reference_value,
            rel_tol=REFERENCE_RELATIVE_TOLERANCE,
            abs_tol=REFERENCE_ABSOLUTE_TOLERANCE,
        )
        label, unit = REFERENCE_LABELS_AND_UNITS[key]
        rows.append(
            {
                "variable": key,
                "label": label,
                "unit": unit,
                "julio_model_value": reference_value,
                "modular_model_value": current_value,
                "absolute_difference": absolute_difference,
                "relative_difference_percent": 100.0 * relative_difference,
                "status": "MATCH" if match else "DIFFERENT",
            }
        )
    return rows


def _latex_escape(value: str) -> str:
    return (
        value.replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("_", r"\_")
    )


def write_performance_table(
    rows: list[dict[str, float | bool | str]],
    output_path: Path,
) -> None:
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Integrated pinch-point model at the reference condition.}",
        r"\label{tab:integrated_pinch_validation}",
        r"\small",
        r"\begin{tabular}{lrrrr}",
        r"\hline",
        (
            r"\textbf{Configuration} & \textbf{$Q_{cond}$} & "
            r"\textbf{$Q_{SC}$} & \textbf{$W_{el}$} & "
            r"\textbf{$COP_{el}$} \\"
        ),
        r" & \textbf{[kW]} & \textbf{[kW]} & \textbf{[kW]} & \\",
        r"\hline",
    ]
    for row in rows:
        lines.append(
            f"{_latex_escape(str(row['architecture']))} & "
            f"{float(row['main_condenser_heat_kW']):.2f} & "
            f"{float(row['subcooler_heat_kW']):.2f} & "
            f"{float(row['total_electrical_power_kW']):.2f} & "
            f"{float(row['overall_COP_electrical']):.3f} \\\\"
        )
    lines.extend(
        [
            r"\hline",
            r"\end{tabular}",
            "",
            r"\vspace{1.5mm}",
            r"\begin{minipage}{0.98\linewidth}",
            r"\footnotesize",
            (
                f"Current condition: {settings.HEATING_CAPACITY_KW:g} kW; "
                "water 110--115 "
                r"$^{\circ}$C at 5 bar; 190 kg/h makeup at 25 "
                r"$^{\circ}$C; $T_{\mathrm{evap,high}}=35$ "
                r"$^{\circ}$C; three pinch points of 10 K."
            ),
            r"\end{minipage}",
            r"\end{table}",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def write_regression_table(
    rows: list[dict[str, float | bool | str]],
    output_path: Path,
) -> None:
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Regression against the supplied pinch-point model.}",
        r"\label{tab:julio_model_regression}",
        r"\small",
        r"\begin{tabular}{lrrrl}",
        r"\hline",
        (
            r"\textbf{Variable} & \textbf{Original} & "
            r"\textbf{Modular} & \textbf{Difference [\%]} & "
            r"\textbf{Status} \\"
        ),
        r"\hline",
    ]
    for row in rows:
        lines.append(
            f"{_latex_escape(str(row['label']))} & "
            f"{float(row['julio_model_value']):.6g} & "
            f"{float(row['modular_model_value']):.6g} & "
            f"{float(row['relative_difference_percent']):+.3e} & "
            f"{row['status']} \\\\"
        )
    lines.extend(
        [
            r"\hline",
            r"\end{tabular}",
            "",
            r"\vspace{1.5mm}",
            r"\begin{minipage}{0.98\linewidth}",
            r"\footnotesize",
            (
                "Both calculations use the original quadratic compressor "
                "correlations at the fixed 35 "
                r"$^{\circ}$C high-stage evaporation point. The reported COP "
                "uses shaft power, as in the supplied model. The current "
                "performance plots use electrical power and the linear "
                "compressor model."
            ),
            r"\end{minipage}",
            r"\end{table}",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def write_validation_report(
    rows: list[dict[str, float | bool | str]],
    regression: list[dict[str, float | bool | str]],
    output_path: Path,
) -> None:
    lines = [
        "# Integrated pinch-point validation",
        "",
        "## Reference condition",
        "",
        "- Product: water heated from 110 to 115 °C at 5 bar.",
        f"- Total useful duty: {settings.HEATING_CAPACITY_KW:g} kW.",
        "- Makeup: 190 kg/h at 25 °C.",
        "- Water path: subcooler, mixture with return, main condenser.",
        "- Refrigerants: R410A in the low stage and R245fa in the high stage.",
        "- High-stage evaporation temperature: 35 °C.",
        "- Evaporator, cascade and condenser pinch points: 10 K.",
        "- Superheat and refrigerant subcooling: 5 K.",
        "- Subcooler effectiveness: 0.90.",
        "- Current architectures: linear compressor-efficiency model.",
        "",
        "## Four-architecture check",
        "",
        "| Configuration | Q cond. [kW] | Q SC [kW] | W el. [kW] | COP el. |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['architecture']} | "
            f"{float(row['main_condenser_heat_kW']):.2f} | "
            f"{float(row['subcooler_heat_kW']):.2f} | "
            f"{float(row['total_electrical_power_kW']):.2f} | "
            f"{float(row['overall_COP_electrical']):.3f} |"
        )
    lines.extend(
        [
            "",
            (
                "PASS_WITH_WARNING means that all balances, pinch points, "
                "water mixing, UA values and compressor-speed checks passed, "
                "but the assumed efficiency correlation reached a clipping "
                "limit. This is a compressor-data warning, not an energy-"
                "balance failure."
            ),
            "",
            "## Regression against the supplied model",
            "",
            "| Variable | Original | Modular | Difference [%] | Status |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for row in regression:
        lines.append(
            f"| {row['label']} [{row['unit']}] | "
            f"{float(row['julio_model_value']):.8g} | "
            f"{float(row['modular_model_value']):.8g} | "
            f"{float(row['relative_difference_percent']):+.3e} | "
            f"{row['status']} |"
        )
    lines.extend(
        [
            "",
            (
                "The regression uses the original quadratic compressor "
                "relations and shaft-based COP. The water-mixing model is an "
                "added downstream balance and does not change the refrigerant-"
                "cycle regression quantities."
            ),
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    rows = solve_reference_architectures()
    regression = julio_regression_rows()
    save_csv(rows, RESULTS_DIRECTORY / "reference_point_validation.csv")
    save_csv(
        regression,
        RESULTS_DIRECTORY / "julio_model_regression.csv",
    )
    write_performance_table(
        rows,
        RESULTS_DIRECTORY / "reference_point_performance_table.tex",
    )
    write_regression_table(
        regression,
        RESULTS_DIRECTORY / "julio_model_regression_table.tex",
    )
    write_validation_report(
        rows,
        regression,
        RESULTS_DIRECTORY / "VALIDATION_REPORT.md",
    )
    failures = [
        row for row in rows if row["validation_status"] == "FAIL"
    ]
    mismatches = [
        row for row in regression if row["status"] != "MATCH"
    ]
    if failures or mismatches:
        raise RuntimeError(
            "A validação encontrou falhas. Consulte VALIDATION_REPORT.md."
        )
    print(f"Integrated validation: results in {RESULTS_DIRECTORY}")


if __name__ == "__main__":
    main()
