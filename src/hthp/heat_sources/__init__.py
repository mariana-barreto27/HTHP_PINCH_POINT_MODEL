"""Modelos das fontes que fornecem calor ao evaporador."""

from hthp.heat_sources.ambient import AmbientHeatSource
from hthp.heat_sources.base import HeatSource, HeatSourceEvaluation
from hthp.heat_sources.fixed_temperature import FixedTemperatureHeatSource
from hthp.heat_sources.pinch_stream import PinchStreamHeatSource
from hthp.heat_sources.process import ProcessHeatSource

__all__ = [
    "AmbientHeatSource",
    "HeatSource",
    "HeatSourceEvaluation",
    "FixedTemperatureHeatSource",
    "PinchStreamHeatSource",
    "ProcessHeatSource",
]
