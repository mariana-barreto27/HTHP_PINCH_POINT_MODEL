"""Consumidores térmicos configuráveis do modelo integrado."""

from hthp.heat_sinks.base import HeatSink, HeatSinkResult, PreparedHeatSink
from hthp.heat_sinks.hot_water import HotWaterHeatSink
from hthp.heat_sinks.steam import SteamHeatSink

__all__ = [
    "HeatSink",
    "HeatSinkResult",
    "PreparedHeatSink",
    "HotWaterHeatSink",
    "SteamHeatSink",
]
