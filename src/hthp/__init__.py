"""Ferramentas modulares para bombas de calor de alta temperatura."""

from hthp.cycles.simple_cycle import (
    SimpleCycleConfig,
    SimpleCycleResult,
    SimpleVaporCompressionCycle,
)
from hthp.heat_sources.ambient import AmbientHeatSource
from hthp.heat_sources.pinch_stream import PinchStreamHeatSource
from hthp.heat_sources.process import ProcessHeatSource
from hthp.cycles.flash_tank_cycle import (
    FlashTankCycle,
    FlashTankCycleConfig,
    FlashTankCycleResult,
)
from hthp.cycles.ihx_bypass_cycle import (
    IHXBypassCycle,
    IHXBypassCycleConfig,
    IHXBypassCycleResult,
)
from hthp.cycles.flash_ihx_cycle import (
    FlashIHXCycle,
    FlashIHXCycleConfig,
    FlashIHXCycleResult,
)
from hthp.cycles.cascade_cycle import (
    CascadeCycle,
    CascadeCycleConfig,
    CascadeCycleResult,
    CascadeStageOptions,
)
from hthp.cycles.integrated_pinch_cascade import (
    IntegratedPinchCascadeConfig,
    IntegratedPinchCascadeCycle,
    IntegratedPinchCascadeResult,
    IntegratedPinchOptimizationResult,
)
from hthp.heat_sinks.hot_water import HotWaterHeatSink
from hthp.heat_sinks.steam import SteamHeatSink
from hthp.pinch import PinchPointConfig
from hthp.components.compressor_performance import (
    CompressorHardwareConfig,
    CompressorHardwareResult,
    LinearPressureRatioEfficiency,
    QuadraticPressureRatioEfficiency,
    VolumetricEfficiencyModel,
    evaluate_compressor_hardware,
)
from hthp.steam.steam_generator import (
    SteamGenerator,
    SteamGeneratorConfig,
    SteamGeneratorResult,
)

__all__ = [
    "AmbientHeatSource",
    "PinchStreamHeatSource",
    "ProcessHeatSource",
    "SimpleCycleConfig",
    "SimpleCycleResult",
    "SimpleVaporCompressionCycle",
    "FlashTankCycle",
    "FlashTankCycleConfig",
    "FlashTankCycleResult",
    "IHXBypassCycle",
    "IHXBypassCycleConfig",
    "IHXBypassCycleResult",
    "FlashIHXCycle",
    "FlashIHXCycleConfig",
    "FlashIHXCycleResult",
    "CascadeCycle",
    "CascadeCycleConfig",
    "CascadeCycleResult",
    "CascadeStageOptions",
    "CompressorHardwareConfig",
    "CompressorHardwareResult",
    "IntegratedPinchCascadeConfig",
    "IntegratedPinchCascadeCycle",
    "IntegratedPinchCascadeResult",
    "IntegratedPinchOptimizationResult",
    "HotWaterHeatSink",
    "LinearPressureRatioEfficiency",
    "SteamHeatSink",
    "PinchPointConfig",
    "QuadraticPressureRatioEfficiency",
    "VolumetricEfficiencyModel",
    "evaluate_compressor_hardware",
    "SteamGenerator",
    "SteamGeneratorConfig",
    "SteamGeneratorResult",
]
