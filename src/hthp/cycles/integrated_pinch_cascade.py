"""Cascata modular com pinch, consumidor e subresfriador integrados."""

from dataclasses import dataclass, field, replace
import math
from typing import Callable, TypeVar

from hthp.components.condenser import Condenser
from hthp.components.compressor_performance import IsentropicEfficiencyModel
from hthp.components.compressor_performance import (
    CompressorHardwareConfig,
    CompressorHardwareResult,
    evaluate_compressor_hardware,
)
from hthp.components.external_subcooler import (
    ExternalSubcooler,
    ExternalSubcoolerConfig,
    ExternalSubcoolerResult,
)
from hthp.components.heat_exchanger_sizing import (
    HeatExchangerSizingResult,
    size_heat_exchanger,
)
from hthp.cycles.cascade_cycle import (
    CascadeCycle,
    CascadeStageOptions,
    CascadeStageResult,
    StageTechnology,
)
from hthp.heat_sinks.base import HeatSink, HeatSinkResult, PreparedHeatSink
from hthp.heat_sinks.steam import SteamHeatSink
from hthp.heat_sources.fixed_temperature import FixedTemperatureHeatSource
from hthp.heat_sources.pinch_stream import PinchStreamHeatSource
from hthp.pinch import PinchPointConfig
from hthp.thermo.properties import (
    critical_temperature_C,
    saturation_pressure_Pa,
)
from hthp.thermo.state import ThermodynamicState


INTERMEDIATE_PRESSURE_TECHNOLOGIES: frozenset[StageTechnology] = frozenset(
    {"flash_tank", "economizer"}
)
INTEGRATED_STAGE_TECHNOLOGIES: frozenset[StageTechnology] = frozenset(
    {"simple", "flash_tank", "economizer"}
)
EvaluationPayload = TypeVar("EvaluationPayload")


@dataclass(frozen=True)
class IntegratedPinchCascadeConfig:
    """Configuração do modo integrado dentro do modelo modular existente."""

    external_heat_source: PinchStreamHeatSource = field(
        default_factory=PinchStreamHeatSource
    )
    heat_sink: HeatSink = field(default_factory=SteamHeatSink)
    pinch_points: PinchPointConfig = field(default_factory=PinchPointConfig)
    external_subcooler: ExternalSubcoolerConfig = field(
        default_factory=ExternalSubcoolerConfig
    )
    low_stage_compressor_hardware: CompressorHardwareConfig = field(
        default_factory=lambda: CompressorHardwareConfig(
            mode="required_speed",
            fixed_displacement_m3_rev=0.0005,
            minimum_speed_Hz=10.0,
            maximum_speed_Hz=100.0,
        )
    )
    high_stage_compressor_hardware: CompressorHardwareConfig = field(
        default_factory=lambda: CompressorHardwareConfig(
            mode="size_displacement",
            fixed_speed_Hz=60.0,
        )
    )
    enforce_compressor_speed_limits: bool = True
    heating_capacity_kW: float = 120.0
    low_stage_refrigerant: str = "R410A"
    high_stage_refrigerant: str = "R245fa"
    low_stage_technology: StageTechnology = "simple"
    high_stage_technology: StageTechnology = "simple"
    low_stage_flash_intermediate_pressure_bar: float | None = None
    high_stage_flash_intermediate_pressure_bar: float | None = None
    low_stage_economizer_intermediate_pressure_bar: float | None = None
    high_stage_economizer_intermediate_pressure_bar: float | None = None
    economizer_effectiveness: float = 0.90
    economizer_minimum_approach_K: float = 5.0
    low_stage_condensation_temperature_C: float = 45.0
    superheat_K: float = 5.0
    subcooling_K: float = 5.0
    compressor_isentropic_efficiency: float = 0.70
    motor_efficiency: float = 0.95
    low_stage_compressor_efficiency_model: (
        IsentropicEfficiencyModel | None
    ) = None
    high_stage_compressor_efficiency_model: (
        IsentropicEfficiencyModel | None
    ) = None
    reject_limited_compressor_efficiencies: bool = False
    heat_exchanger_correction_factor: float = 1.0
    optimization_high_stage_evaporation_minimum_C: float = 20.0
    optimization_high_stage_evaporation_maximum_C: float = 60.0
    optimization_step_K: float = 0.5
    optimization_tolerance_K: float = 0.01
    optimization_maximum_iterations: int = 80
    optimize_flash_pressures: bool = True
    flash_optimization_points: int = 11
    flash_refinement_iterations: int = 24
    flash_log_fraction_tolerance: float = 1.0e-5
    flash_minimum_log_fraction: float = 0.05
    flash_maximum_log_fraction: float = 0.95
    external_subcooler_iteration_tolerance_kW: float = 1.0e-8
    external_subcooler_maximum_iterations: int = 60

    def __post_init__(self) -> None:
        if self.heating_capacity_kW <= 0.0:
            raise ValueError("A capacidade útil deve ser positiva.")
        if self.superheat_K <= 0.0 or self.subcooling_K < 0.0:
            raise ValueError("Superaquecimento/subresfriamento inválidos.")
        if not 0.0 < self.motor_efficiency <= 1.0:
            raise ValueError("A eficiência do motor deve estar entre zero e um.")
        if not 0.0 < self.compressor_isentropic_efficiency <= 1.0:
            raise ValueError(
                "A eficiência isentrópica deve estar entre zero e um."
            )
        if self.low_stage_technology not in INTEGRATED_STAGE_TECHNOLOGIES:
            raise ValueError(
                "O modelo integrado de pinch não utiliza IHX no estágio baixo."
            )
        if self.high_stage_technology not in INTEGRATED_STAGE_TECHNOLOGIES:
            raise ValueError(
                "O modelo integrado de pinch não utiliza IHX no estágio alto."
            )
        if not 0.0 < self.economizer_effectiveness <= 1.0:
            raise ValueError("A efetividade do economizador deve estar entre 0 e 1.")
        if self.economizer_minimum_approach_K < 0.0:
            raise ValueError("O pinch do economizador não pode ser negativo.")
        if not 0.0 < self.heat_exchanger_correction_factor <= 1.0:
            raise ValueError("O fator de correção deve estar entre zero e um.")
        if self.optimization_step_K <= 0.0:
            raise ValueError("O passo da otimização deve ser positivo.")
        if self.optimization_tolerance_K <= 0.0:
            raise ValueError("A tolerância da otimização deve ser positiva.")
        if self.optimization_maximum_iterations < 1:
            raise ValueError(
                "O número de iterações da otimização deve ser positivo."
            )
        if (
            self.optimization_high_stage_evaporation_maximum_C
            <= self.optimization_high_stage_evaporation_minimum_C
        ):
            raise ValueError("A faixa de otimização da cascata é inválida.")
        if self.flash_optimization_points < 3:
            raise ValueError("A otimização do flash exige pelo menos três pontos.")
        if self.flash_refinement_iterations < 1:
            raise ValueError("O refinamento do flash exige pelo menos uma iteração.")
        if self.flash_log_fraction_tolerance <= 0.0:
            raise ValueError("A tolerância da pressão de flash deve ser positiva.")
        if not (
            0.0
            < self.flash_minimum_log_fraction
            < self.flash_maximum_log_fraction
            < 1.0
        ):
            raise ValueError("A faixa logarítmica do flash é inválida.")
        if self.external_subcooler_iteration_tolerance_kW <= 0.0:
            raise ValueError("A tolerância do subresfriador deve ser positiva.")
        if self.external_subcooler_maximum_iterations < 1:
            raise ValueError("O número máximo de iterações deve ser positivo.")
        if not math.isclose(
            self.external_heat_source.evaporator_pinch_K,
            self.pinch_points.evaporator_K,
            abs_tol=1.0e-9,
        ):
            raise ValueError(
                "O pinch da fonte deve coincidir com o pinch do evaporador."
            )

    def stage_options(self, stage: str) -> CascadeStageOptions:
        if stage == "low":
            refrigerant = self.low_stage_refrigerant
            technology = self.low_stage_technology
            flash_pressure = self.low_stage_flash_intermediate_pressure_bar
            economizer_pressure = (
                self.low_stage_economizer_intermediate_pressure_bar
            )
            efficiency_model = self.low_stage_compressor_efficiency_model
        elif stage == "high":
            refrigerant = self.high_stage_refrigerant
            technology = self.high_stage_technology
            flash_pressure = self.high_stage_flash_intermediate_pressure_bar
            economizer_pressure = (
                self.high_stage_economizer_intermediate_pressure_bar
            )
            efficiency_model = self.high_stage_compressor_efficiency_model
        else:
            raise ValueError(f"Estágio desconhecido: {stage}.")
        return CascadeStageOptions(
            refrigerant=refrigerant,
            technology=technology,
            superheat_K=self.superheat_K,
            subcooling_K=self.subcooling_K,
            compressor_isentropic_efficiency=(
                self.compressor_isentropic_efficiency
            ),
            motor_efficiency=self.motor_efficiency,
            compressor_efficiency_model=efficiency_model,
            flash_intermediate_pressure_bar=flash_pressure,
            economizer_intermediate_pressure_bar=economizer_pressure,
            economizer_effectiveness=self.economizer_effectiveness,
            economizer_minimum_approach_K=(
                self.economizer_minimum_approach_K
            ),
        )


@dataclass(frozen=True)
class IntegratedHighStageResult:
    technology: StageTechnology
    refrigerant: str
    evaporation_temperature_C: float
    condensation_temperature_C: float
    states: dict[str, ThermodynamicState]
    refrigerant_mass_flow_kg_s: float
    main_condenser_heat_kW: float
    external_subcooler_heat_kW: float
    total_useful_heat_kW: float
    evaporator_heat_kW: float
    compressor_shaft_power_kW: float
    compressor_electrical_power_kW: float
    heating_COP_shaft: float
    heating_COP_electrical: float
    pressure_ratio: float
    intermediate_pressure_bar: float | None
    compressor_isentropic_efficiencies: tuple[float, ...]
    energy_balance_error_kW: float
    external_subcooler: ExternalSubcoolerResult
    stage: CascadeStageResult


@dataclass(frozen=True)
class IntegratedPinchCascadeResult:
    config: IntegratedPinchCascadeConfig
    low_stage_condensation_temperature_C: float
    high_stage_evaporation_temperature_C: float
    low_stage: CascadeStageResult
    high_stage: IntegratedHighStageResult
    heat_sink: HeatSinkResult
    heat_exchangers: dict[str, HeatExchangerSizingResult]
    low_stage_compressors: tuple[CompressorHardwareResult, ...]
    high_stage_compressors: tuple[CompressorHardwareResult, ...]
    source_mass_flow_kg_s: float
    interstage_heat_balance_error_kW: float
    total_shaft_power_kW: float
    total_electrical_power_kW: float
    overall_COP_shaft: float
    overall_COP_electrical: float
    overall_energy_balance_error_kW: float


@dataclass(frozen=True)
class IntegratedPinchOptimizationResult:
    optimum: IntegratedPinchCascadeResult
    valid_points: tuple[IntegratedPinchCascadeResult, ...]
    invalid_point_count: int
    optimum_at_temperature_boundary: bool
    optimization_method: str = "continuous_golden_section"
    function_evaluations: int = 0


class IntegratedPinchCascadeCycle:
    """Resolve todas as arquiteturas sem remover o modo anterior de 5 K."""

    def __init__(self, config: IntegratedPinchCascadeConfig) -> None:
        self.config = config

    def _intermediate_option_at_log_fraction(
        self,
        options: CascadeStageOptions,
        evaporation_temperature_C: float,
        condensation_temperature_C: float,
        log_fraction: float,
    ) -> CascadeStageOptions:
        low_pressure = saturation_pressure_Pa(
            options.refrigerant,
            evaporation_temperature_C,
            quality=1.0,
        )
        high_pressure = saturation_pressure_Pa(
            options.refrigerant,
            condensation_temperature_C,
            quality=0.0,
        )
        log_low = math.log(low_pressure)
        log_high = math.log(high_pressure)
        pressure_bar = math.exp(
            log_low + log_fraction * (log_high - log_low)
        ) / 1.0e5
        if options.technology == "flash_tank":
            return replace(
                options,
                flash_intermediate_pressure_bar=pressure_bar,
            )
        if options.technology == "economizer":
            return replace(
                options,
                economizer_intermediate_pressure_bar=pressure_bar,
            )
        raise ValueError("A tecnologia não utiliza pressão intermediária.")

    @staticmethod
    def _intermediate_pressure_bar(
        options: CascadeStageOptions,
    ) -> float | None:
        if options.technology == "flash_tank":
            return options.flash_intermediate_pressure_bar
        if options.technology == "economizer":
            return options.economizer_intermediate_pressure_bar
        return None

    def _optimize_stage_option(
        self,
        options: CascadeStageOptions,
        evaporation_temperature_C: float,
        condensation_temperature_C: float,
        evaluator: Callable[
            [CascadeStageOptions], tuple[float, EvaluationPayload]
        ],
    ) -> tuple[CascadeStageOptions, EvaluationPayload]:
        """Busca global grosseira seguida de refinamento na pressão logarítmica."""
        config = self.config
        if (
            options.technology not in INTERMEDIATE_PRESSURE_TECHNOLOGIES
            or self._intermediate_pressure_bar(options) is not None
            or not config.optimize_flash_pressures
        ):
            _, payload = evaluator(options)
            return options, payload

        lower = config.flash_minimum_log_fraction
        upper = config.flash_maximum_log_fraction
        count = config.flash_optimization_points
        fractions = [
            lower + (upper - lower) * index / (count - 1)
            for index in range(count)
        ]
        evaluated: dict[
            float,
            tuple[float, CascadeStageOptions, EvaluationPayload],
        ] = {}

        def evaluate_fraction(
            fraction: float,
        ) -> tuple[float, CascadeStageOptions, EvaluationPayload] | None:
            key = round(fraction, 14)
            if key in evaluated:
                return evaluated[key]
            candidate = self._intermediate_option_at_log_fraction(
                options,
                evaporation_temperature_C,
                condensation_temperature_C,
                fraction,
            )
            try:
                objective, payload = evaluator(candidate)
            except (ValueError, OverflowError):
                return None
            if not math.isfinite(objective):
                return None
            result = (objective, candidate, payload)
            evaluated[key] = result
            return result

        coarse_results = [
            result
            for fraction in fractions
            if (result := evaluate_fraction(fraction)) is not None
        ]
        if not coarse_results:
            raise ValueError("Nenhuma pressão intermediária é válida.")
        coarse_best = min(coarse_results, key=lambda item: item[0])
        best_pressure = self._intermediate_pressure_bar(coarse_best[1])
        best_index = min(
            range(count),
            key=lambda index: abs(
                float(
                    self._intermediate_pressure_bar(
                        self._intermediate_option_at_log_fraction(
                            options,
                            evaporation_temperature_C,
                            condensation_temperature_C,
                            fractions[index],
                        )
                    )
                )
                - float(best_pressure)
            ),
        )
        left = fractions[max(0, best_index - 1)]
        right = fractions[min(count - 1, best_index + 1)]
        golden_ratio = (math.sqrt(5.0) - 1.0) / 2.0

        x_left = right - golden_ratio * (right - left)
        x_right = left + golden_ratio * (right - left)
        left_result = evaluate_fraction(x_left)
        right_result = evaluate_fraction(x_right)
        for _ in range(config.flash_refinement_iterations):
            if right - left <= config.flash_log_fraction_tolerance:
                break
            left_value = math.inf if left_result is None else left_result[0]
            right_value = math.inf if right_result is None else right_result[0]
            if left_value <= right_value:
                right = x_right
                x_right = x_left
                right_result = left_result
                x_left = right - golden_ratio * (right - left)
                left_result = evaluate_fraction(x_left)
            else:
                left = x_left
                x_left = x_right
                left_result = right_result
                x_right = left + golden_ratio * (right - left)
                right_result = evaluate_fraction(x_right)

        best = min(evaluated.values(), key=lambda item: item[0])
        return best[1], best[2]

    def _solve_high_stage_option(
        self,
        options: CascadeStageOptions,
        evaporation_temperature_C: float,
        condensation_temperature_C: float,
        main_condenser_heat_kW: float,
        external_subcooler_heat_kW: float,
        prepared_sink: PreparedHeatSink,
        condenser_outlet: ThermodynamicState,
    ) -> tuple[IntegratedHighStageResult, HeatSinkResult]:
        config = self.config
        source = FixedTemperatureHeatSource(evaporation_temperature_C)
        specific_external_heat = 0.0
        stage: CascadeStageResult | None = None
        for _ in range(config.external_subcooler_maximum_iterations):
            stage = CascadeCycle.solve_stage(
                replace(
                    options,
                    external_subcooling_specific_heat_kJ_kg=(
                        specific_external_heat
                    ),
                ),
                source,
                condensation_temperature_C,
                main_condenser_heat_kW,
            )
            error_kW = (
                stage.external_subcooler_heat_kW
                - external_subcooler_heat_kW
            )
            if abs(error_kW) <= (
                config.external_subcooler_iteration_tolerance_kW
            ):
                break
            target_specific_heat = (
                external_subcooler_heat_kW
                / stage.refrigerant_mass_flow_kg_s
            )
            specific_external_heat = target_specific_heat
        else:
            raise ValueError("O acoplamento do subresfriador não convergiu.")
        if stage is None:
            raise RuntimeError("O estágio alto não foi resolvido.")
        self._validate_compressor_efficiency_range(stage)

        external_subcooler = ExternalSubcooler(
            config.external_subcooler
        ).solve(
            config.high_stage_refrigerant,
            condenser_outlet,
            stage.refrigerant_mass_flow_kg_s,
            prepared_sink.subcooler_cold_stream,
            prescribed_heat_kW=external_subcooler_heat_kW,
        )
        heat_sink_result = config.heat_sink.evaluate(
            prepared_sink,
            main_condenser_heat_kW,
            external_subcooler_heat_kW,
            external_subcooler.cold_outlet_temperature_C,
        )
        total_useful_heat = (
            main_condenser_heat_kW + external_subcooler_heat_kW
        )
        minimum_pressure = min(
            state.pressure_Pa for state in stage.states.values()
        )
        intermediate_pressure_bar = (
            stage.intermediate_pressure_bar
            if options.technology in INTERMEDIATE_PRESSURE_TECHNOLOGIES
            else None
        )
        high_result = IntegratedHighStageResult(
            technology=options.technology,
            refrigerant=options.refrigerant,
            evaporation_temperature_C=evaporation_temperature_C,
            condensation_temperature_C=condensation_temperature_C,
            states=stage.states,
            refrigerant_mass_flow_kg_s=stage.refrigerant_mass_flow_kg_s,
            main_condenser_heat_kW=main_condenser_heat_kW,
            external_subcooler_heat_kW=external_subcooler_heat_kW,
            total_useful_heat_kW=total_useful_heat,
            evaporator_heat_kW=stage.evaporator_heat_kW,
            compressor_shaft_power_kW=stage.shaft_power_kW,
            compressor_electrical_power_kW=stage.electrical_power_kW,
            heating_COP_shaft=total_useful_heat / stage.shaft_power_kW,
            heating_COP_electrical=(
                total_useful_heat / stage.electrical_power_kW
            ),
            pressure_ratio=condenser_outlet.pressure_Pa / minimum_pressure,
            intermediate_pressure_bar=intermediate_pressure_bar,
            compressor_isentropic_efficiencies=(
                stage.compressor_isentropic_efficiencies
            ),
            energy_balance_error_kW=(
                total_useful_heat
                - stage.evaporator_heat_kW
                - stage.shaft_power_kW
            ),
            external_subcooler=external_subcooler,
            stage=stage,
        )
        return high_result, heat_sink_result

    def _select_low_stage_options(
        self,
        low_condensation_temperature_C: float,
    ) -> CascadeStageOptions:
        config = self.config
        base_options = config.stage_options("low")

        def evaluate(
            candidate: CascadeStageOptions,
        ) -> tuple[float, CascadeStageResult]:
            result = CascadeCycle.solve_stage(
                candidate,
                config.external_heat_source,
                low_condensation_temperature_C,
                1.0,
            )
            self._validate_compressor_efficiency_range(result)
            return result.electrical_power_kW, result

        optimum, _ = self._optimize_stage_option(
            base_options,
            config.external_heat_source.evaporation_temperature_C(),
            low_condensation_temperature_C,
            evaluate,
        )
        return optimum

    def _validate_compressor_efficiency_range(
        self,
        stage: CascadeStageResult,
    ) -> None:
        """Não deixa a otimização explorar o piso/teto artificial da curva."""
        if not self.config.reject_limited_compressor_efficiencies:
            return
        limited = [
            (index, raw, status)
            for index, (raw, status) in enumerate(
                zip(
                    stage.compressor_raw_isentropic_efficiencies,
                    stage.compressor_efficiency_limit_statuses,
                    strict=True,
                ),
                start=1,
            )
            if status != "none"
        ]
        if limited:
            details = ", ".join(
                f"compressor {index}: eta_raw={raw:.4f} ({status})"
                for index, raw, status in limited
            )
            raise ValueError(
                "Ponto fora da faixa útil da correlação de eficiência: "
                + details
            )

    def _solve_low_stage(
        self,
        options: CascadeStageOptions,
        low_condensation_temperature_C: float,
        condenser_heat_kW: float,
    ) -> CascadeStageResult:
        return CascadeCycle.solve_stage(
            options,
            self.config.external_heat_source,
            low_condensation_temperature_C,
            condenser_heat_kW,
        )

    @staticmethod
    def _evaluate_stage_compressors(
        stage: CascadeStageResult,
        hardware: CompressorHardwareConfig,
    ) -> tuple[CompressorHardwareResult, ...]:
        results: list[CompressorHardwareResult] = []
        for mass_flow, suction_key, discharge_pressure in zip(
            stage.compressor_mass_flows_kg_s,
            stage.compressor_suction_state_keys,
            stage.compressor_discharge_pressures_Pa,
            strict=True,
        ):
            results.append(
                evaluate_compressor_hardware(
                    stage.refrigerant,
                    stage.states[suction_key],
                    discharge_pressure,
                    mass_flow,
                    hardware,
                )
            )
        return tuple(results)

    def solve(
        self,
        low_stage_condensation_temperature_C: float | None = None,
    ) -> IntegratedPinchCascadeResult:
        config = self.config
        low_condensation_temperature_C = (
            config.low_stage_condensation_temperature_C
            if low_stage_condensation_temperature_C is None
            else low_stage_condensation_temperature_C
        )
        if low_condensation_temperature_C >= critical_temperature_C(
            config.low_stage_refrigerant
        ):
            raise ValueError("A condensação do estágio baixo supera o ponto crítico.")
        high_evaporation_temperature_C = (
            low_condensation_temperature_C - config.pinch_points.cascade_K
        )
        prepared_sink = config.heat_sink.prepare(
            config.heating_capacity_kW,
            config.pinch_points.condenser_K,
        )
        high_condensation_temperature_C = (
            prepared_sink.condensation_temperature_C
        )
        if high_condensation_temperature_C >= critical_temperature_C(
            config.high_stage_refrigerant
        ):
            raise ValueError("A condensação do estágio alto supera o ponto crítico.")
        if (
            high_evaporation_temperature_C + config.superheat_K
            >= high_condensation_temperature_C
        ):
            raise ValueError("Os níveis térmicos do estágio alto são incompatíveis.")

        condenser_outlet = Condenser(
            high_condensation_temperature_C,
            config.subcooling_K,
        ).outlet_state(config.high_stage_refrigerant)
        external_subcooler_heat_kW, _ = ExternalSubcooler(
            config.external_subcooler
        ).estimate_heat_kW(
            condenser_outlet,
            prepared_sink.subcooler_cold_stream,
        )
        main_condenser_heat_kW = (
            config.heating_capacity_kW - external_subcooler_heat_kW
        )
        if main_condenser_heat_kW <= 0.0:
            raise ValueError("O subresfriador excede a carga útil total.")

        low_options = self._select_low_stage_options(
            low_condensation_temperature_C
        )

        def evaluate_high(
            high_options: CascadeStageOptions,
        ) -> tuple[
            float,
            tuple[
                IntegratedHighStageResult,
                HeatSinkResult,
                CascadeStageResult,
            ],
        ]:
            high_stage, heat_sink = self._solve_high_stage_option(
                high_options,
                high_evaporation_temperature_C,
                high_condensation_temperature_C,
                main_condenser_heat_kW,
                external_subcooler_heat_kW,
                prepared_sink,
                condenser_outlet,
            )
            low_stage = self._solve_low_stage(
                low_options,
                low_condensation_temperature_C,
                high_stage.evaporator_heat_kW,
            )
            low_compressors = self._evaluate_stage_compressors(
                low_stage,
                config.low_stage_compressor_hardware,
            )
            if (
                config.enforce_compressor_speed_limits
                and not all(
                    compressor.speed_feasible
                    for compressor in low_compressors
                )
            ):
                raise ValueError(
                    "A rotação requerida no estágio baixo está fora da faixa."
                )
            total_power = (
                high_stage.compressor_electrical_power_kW
                + low_stage.electrical_power_kW
            )
            return total_power, (high_stage, heat_sink, low_stage)

        _, selected = self._optimize_stage_option(
            config.stage_options("high"),
            high_evaporation_temperature_C,
            high_condensation_temperature_C,
            evaluate_high,
        )
        high_stage, heat_sink, low_stage = selected
        low_compressors = self._evaluate_stage_compressors(
            low_stage,
            config.low_stage_compressor_hardware,
        )
        high_compressors = self._evaluate_stage_compressors(
            high_stage.stage,
            config.high_stage_compressor_hardware,
        )

        source_mass_flow = config.external_heat_source.mass_flow_for_heat_kg_s(
            low_stage.evaporator_heat_kW
        )
        correction = config.heat_exchanger_correction_factor
        high_condenser_sizing = size_heat_exchanger(
            high_stage.main_condenser_heat_kW,
            high_stage.condensation_temperature_C
            - heat_sink.main_inlet_temperature_C,
            high_stage.condensation_temperature_C
            - heat_sink.main_outlet_temperature_C,
            correction,
        )
        cascade_sizing = size_heat_exchanger(
            high_stage.evaporator_heat_kW,
            config.pinch_points.cascade_K,
            config.pinch_points.cascade_K,
            correction,
        )
        source = config.external_heat_source
        low_evaporator_sizing = size_heat_exchanger(
            low_stage.evaporator_heat_kW,
            source.inlet_temperature_C - low_stage.evaporation_temperature_C,
            source.outlet_temperature_C - low_stage.evaporation_temperature_C,
            correction,
        )

        total_shaft_power = (
            high_stage.compressor_shaft_power_kW + low_stage.shaft_power_kW
        )
        total_electrical_power = (
            high_stage.compressor_electrical_power_kW
            + low_stage.electrical_power_kW
        )
        total_heat = high_stage.total_useful_heat_kW
        return IntegratedPinchCascadeResult(
            config=config,
            low_stage_condensation_temperature_C=low_condensation_temperature_C,
            high_stage_evaporation_temperature_C=(
                high_evaporation_temperature_C
            ),
            low_stage=low_stage,
            high_stage=high_stage,
            heat_sink=heat_sink,
            heat_exchangers={
                "high_stage_condenser": high_condenser_sizing,
                "external_subcooler": high_stage.external_subcooler.sizing,
                "cascade": cascade_sizing,
                "low_stage_evaporator": low_evaporator_sizing,
            },
            low_stage_compressors=low_compressors,
            high_stage_compressors=high_compressors,
            source_mass_flow_kg_s=source_mass_flow,
            interstage_heat_balance_error_kW=(
                low_stage.condenser_heat_kW - high_stage.evaporator_heat_kW
            ),
            total_shaft_power_kW=total_shaft_power,
            total_electrical_power_kW=total_electrical_power,
            overall_COP_shaft=total_heat / total_shaft_power,
            overall_COP_electrical=total_heat / total_electrical_power,
            overall_energy_balance_error_kW=(
                total_heat - low_stage.evaporator_heat_kW - total_shaft_power
            ),
        )

    def optimize_intermediate_temperature(
        self,
    ) -> IntegratedPinchOptimizationResult:
        config = self.config
        lower = config.optimization_high_stage_evaporation_minimum_C
        upper = config.optimization_high_stage_evaporation_maximum_C
        valid: list[IntegratedPinchCascadeResult] = []
        invalid_count = 0
        candidate = lower
        while candidate <= upper + 0.5 * config.optimization_step_K:
            try:
                valid.append(
                    self.solve(candidate + config.pinch_points.cascade_K)
                )
            except (ValueError, OverflowError):
                invalid_count += 1
            candidate += config.optimization_step_K
        if not valid:
            raise ValueError("Nenhuma temperatura intermediária viável.")
        evaluated: dict[float, IntegratedPinchCascadeResult] = {
            round(result.high_stage_evaporation_temperature_C, 10): result
            for result in valid
        }

        def evaluate(
            temperature_C: float,
        ) -> IntegratedPinchCascadeResult | None:
            key = round(temperature_C, 10)
            if key in evaluated:
                return evaluated[key]
            try:
                result = self.solve(
                    temperature_C + config.pinch_points.cascade_K
                )
            except (ValueError, OverflowError):
                return None
            evaluated[key] = result
            return result

        # A malha identifica os máximos locais e os limites de cada trecho
        # viável. Depois, cada candidato é refinado por seção áurea.
        grid = sorted(
            valid,
            key=lambda result: result.high_stage_evaporation_temperature_C,
        )
        candidate_intervals: list[tuple[float, float]] = []
        for index, result in enumerate(grid):
            value = result.overall_COP_electrical
            left_is_adjacent = (
                index > 0
                and result.high_stage_evaporation_temperature_C
                - grid[index - 1].high_stage_evaporation_temperature_C
                <= 1.5 * config.optimization_step_K
            )
            right_is_adjacent = (
                index + 1 < len(grid)
                and grid[index + 1].high_stage_evaporation_temperature_C
                - result.high_stage_evaporation_temperature_C
                <= 1.5 * config.optimization_step_K
            )
            left_value = (
                grid[index - 1].overall_COP_electrical
                if left_is_adjacent
                else -math.inf
            )
            right_value = (
                grid[index + 1].overall_COP_electrical
                if right_is_adjacent
                else -math.inf
            )
            if value >= left_value and value >= right_value:
                left = (
                    grid[index - 1].high_stage_evaporation_temperature_C
                    if left_is_adjacent
                    else result.high_stage_evaporation_temperature_C
                )
                right = (
                    grid[index + 1].high_stage_evaporation_temperature_C
                    if right_is_adjacent
                    else result.high_stage_evaporation_temperature_C
                )
                if right > left:
                    candidate_intervals.append((left, right))

        golden_ratio = (math.sqrt(5.0) - 1.0) / 2.0
        for interval_left, interval_right in candidate_intervals:
            left = interval_left
            right = interval_right
            x_left = right - golden_ratio * (right - left)
            x_right = left + golden_ratio * (right - left)
            result_left = evaluate(x_left)
            result_right = evaluate(x_right)
            for _ in range(config.optimization_maximum_iterations):
                if right - left <= config.optimization_tolerance_K:
                    break
                value_left = (
                    -math.inf
                    if result_left is None
                    else result_left.overall_COP_electrical
                )
                value_right = (
                    -math.inf
                    if result_right is None
                    else result_right.overall_COP_electrical
                )
                if value_left >= value_right:
                    right = x_right
                    x_right = x_left
                    result_right = result_left
                    x_left = right - golden_ratio * (right - left)
                    result_left = evaluate(x_left)
                else:
                    left = x_left
                    x_left = x_right
                    result_left = result_right
                    x_right = left + golden_ratio * (right - left)
                    result_right = evaluate(x_right)

        optimum = max(
            evaluated.values(),
            key=lambda result: result.overall_COP_electrical,
        )
        return IntegratedPinchOptimizationResult(
            optimum=optimum,
            valid_points=tuple(valid),
            invalid_point_count=invalid_count,
            optimum_at_temperature_boundary=(
                math.isclose(
                    optimum.high_stage_evaporation_temperature_C,
                    lower,
                    abs_tol=0.5 * config.optimization_step_K,
                )
                or math.isclose(
                    optimum.high_stage_evaporation_temperature_C,
                    upper,
                    abs_tol=0.5 * config.optimization_step_K,
                )
            ),
            function_evaluations=len(evaluated),
        )
