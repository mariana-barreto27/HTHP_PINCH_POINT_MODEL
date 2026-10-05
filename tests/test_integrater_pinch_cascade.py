"""Testes do pinch point integrado no mesmo modelo modular."""

from pathlib import Path
from dataclasses import replace
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from hthp.cycles.integrated_pinch_cascade import (  # noqa: E402
    IntegratedPinchCascadeConfig,
    IntegratedPinchCascadeCycle,
)
from hthp.components.compressor_performance import (  # noqa: E402
    QuadraticPressureRatioEfficiency,
)
from hthp.heat_sinks.hot_water import HotWaterHeatSink  # noqa: E402


class IntegratedPinchCascadeTests(unittest.TestCase):
    def solve(self, heat_sink=None):
        arguments = {} if heat_sink is None else {"heat_sink": heat_sink}
        return IntegratedPinchCascadeCycle(
            IntegratedPinchCascadeConfig(**arguments)
        ).solve()

    def test_steam_mode_has_three_ten_kelvin_pinches(self) -> None:
        result = self.solve()
        source = result.config.external_heat_source
        self.assertAlmostEqual(
            source.outlet_temperature_C
            - result.low_stage.evaporation_temperature_C,
            10.0,
        )
        self.assertAlmostEqual(
            result.low_stage_condensation_temperature_C
            - result.high_stage_evaporation_temperature_C,
            10.0,
        )
        self.assertAlmostEqual(
            result.high_stage.condensation_temperature_C
            - result.heat_sink.final_outlet_temperature_C,
            10.0,
        )

    def test_total_duty_includes_external_subcooler(self) -> None:
        result = self.solve()
        self.assertAlmostEqual(
            result.high_stage.main_condenser_heat_kW
            + result.high_stage.external_subcooler_heat_kW,
            120.0,
            places=10,
        )
        self.assertGreater(result.high_stage.external_subcooler_heat_kW, 0.0)
        self.assertAlmostEqual(result.heat_sink.final_outlet_quality, 1.0)

    def test_cascade_energy_balances_and_ua(self) -> None:
        result = self.solve()
        self.assertAlmostEqual(result.interstage_heat_balance_error_kW, 0.0)
        self.assertAlmostEqual(result.overall_energy_balance_error_kW, 0.0)
        self.assertAlmostEqual(result.heat_sink.energy_balance_error_kW, 0.0)
        for sizing in result.heat_exchangers.values():
            self.assertGreater(sizing.lmtd_K, 0.0)
            self.assertGreater(sizing.ua_kW_K, 0.0)

    def test_hot_water_streams_are_mixed_before_the_condenser(self) -> None:
        result = self.solve(HotWaterHeatSink())
        sink = result.heat_sink
        self.assertAlmostEqual(
            sink.final_stream_mass_flow_kg_s,
            sink.main_stream_mass_flow_kg_s
            + sink.subcooler_stream_mass_flow_kg_s,
        )
        self.assertAlmostEqual(
            sink.final_outlet_temperature_C,
            sink.main_outlet_temperature_C,
        )
        self.assertGreater(sink.main_inlet_temperature_C, 110.0)
        self.assertLess(
            sink.main_inlet_temperature_C,
            sink.subcooler_outlet_temperature_C,
        )
        self.assertGreater(sink.main_stream_mass_flow_kg_s, 0.0)
        self.assertAlmostEqual(sink.energy_balance_error_kW, 0.0, places=10)

    def test_intermediate_temperature_optimization(self) -> None:
        solver = IntegratedPinchCascadeCycle(IntegratedPinchCascadeConfig())
        fixed = solver.solve()
        optimization = solver.optimize_intermediate_temperature()
        optimum = optimization.optimum
        self.assertGreaterEqual(
            optimum.overall_COP_electrical,
            fixed.overall_COP_electrical,
        )
        self.assertGreaterEqual(
            optimum.high_stage_evaporation_temperature_C,
            20.0,
        )
        self.assertLessEqual(
            optimum.high_stage_evaporation_temperature_C,
            60.0,
        )

    def test_all_requested_architectures_use_the_integrated_balance(self) -> None:
        architectures = [
            ("simple", "simple"),
            ("flash_tank", "simple"),
            ("simple", "flash_tank"),
            ("flash_tank", "flash_tank"),
        ]
        base = IntegratedPinchCascadeConfig(flash_optimization_points=5)
        for low, high in architectures:
            with self.subTest(low=low, high=high):
                result = IntegratedPinchCascadeCycle(
                    replace(
                        base,
                        low_stage_technology=low,
                        high_stage_technology=high,
                    )
                ).solve()
                self.assertAlmostEqual(
                    result.high_stage.main_condenser_heat_kW
                    + result.high_stage.external_subcooler_heat_kW,
                    120.0,
                )
                self.assertLess(
                    abs(result.overall_energy_balance_error_kW),
                    1.0e-6,
                )
                self.assertGreater(result.overall_COP_electrical, 1.0)

    def test_integrated_model_rejects_ihx_technologies(self) -> None:
        with self.assertRaisesRegex(ValueError, "não utiliza IHX"):
            IntegratedPinchCascadeConfig(
                high_stage_technology="ihx_bypass"
            )

    def test_flash_pressure_search_does_not_reduce_overall_cop(self) -> None:
        base = IntegratedPinchCascadeConfig(
            low_stage_technology="flash_tank",
            high_stage_technology="flash_tank",
            flash_optimization_points=11,
        )
        geometric = IntegratedPinchCascadeCycle(
            replace(base, optimize_flash_pressures=False)
        ).solve()
        optimized = IntegratedPinchCascadeCycle(base).solve()
        self.assertGreaterEqual(
            optimized.overall_COP_electrical,
            geometric.overall_COP_electrical,
        )
        self.assertIsNotNone(optimized.low_stage.intermediate_pressure_bar)
        self.assertIsNotNone(optimized.high_stage.intermediate_pressure_bar)

    def test_economizer_architectures_close_integrated_balances(self) -> None:
        architectures = [
            ("economizer", "simple"),
            ("simple", "economizer"),
            ("economizer", "economizer"),
        ]
        base = IntegratedPinchCascadeConfig(flash_optimization_points=5)
        for low, high in architectures:
            with self.subTest(low=low, high=high):
                result = IntegratedPinchCascadeCycle(
                    replace(
                        base,
                        low_stage_technology=low,
                        high_stage_technology=high,
                    )
                ).solve()
                self.assertLess(
                    abs(result.overall_energy_balance_error_kW),
                    1.0e-6,
                )
                self.assertGreater(result.overall_COP_electrical, 1.0)
                if low == "economizer":
                    self.assertIsNotNone(
                        result.low_stage.injection_mass_fraction
                    )
                if high == "economizer":
                    self.assertIsNotNone(
                        result.high_stage.stage.injection_mass_fraction
                    )

    def test_reference_curve_extrapolation_is_rejected_when_requested(self) -> None:
        high_curve = QuadraticPressureRatioEfficiency(
            -0.29,
            0.33,
            -0.027,
        )
        solver = IntegratedPinchCascadeCycle(
            IntegratedPinchCascadeConfig(
                high_stage_compressor_efficiency_model=high_curve,
                reject_limited_compressor_efficiencies=True,
            )
        )
        with self.assertRaisesRegex(ValueError, "faixa"):
            solver.solve(30.0)
        valid = solver.solve(50.0)
        self.assertEqual(
            valid.high_stage.stage.compressor_efficiency_limit_statuses,
            ("none",),
        )


if __name__ == "__main__":
    unittest.main()
