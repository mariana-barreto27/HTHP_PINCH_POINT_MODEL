"""Exact CoolProp properties using reusable low-level states and SI units."""

from collections import OrderedDict
from functools import lru_cache
import math
import os
from threading import local

from CoolProp.CoolProp import (AbstractState, extract_backend, extract_fractions,
                               generate_update_pair, get_parameter_index)


KELVIN_OFFSET = 273.15

# Current refrigerants are recognized directly. Keep aliases for callers
# without changing refrigerants, composition, backend or reference states.
REFRIGERANT_ALIASES = {}
_STATE_POOL = local()
_MAX_STATES_PER_THREAD = 16


class _StateHandle:
    def __init__(self, state):
        self.state = state
        self.last_inputs = None


@lru_cache(maxsize=128)
def _parameter_index(name):
    return get_parameter_index(name)


def _state_handle(refrigerant):
    # AbstractState is mutable: do not share it across threads or reuse an
    # inherited backend after a process fork. Only immutable results are cached.
    process = os.getpid()
    if getattr(_STATE_POOL, "process", None) != process:
        _STATE_POOL.process = process
        _STATE_POOL.states = OrderedDict()
    states = _STATE_POOL.states
    fluid = resolve_refrigerant(refrigerant)
    handle = states.get(fluid)
    if handle is None:
        backend, specification = extract_backend(fluid)
        names, fractions = extract_fractions(specification)
        state = AbstractState("HEOS" if backend == "?" else backend, "&".join(names))
        if fractions:
            if state.using_mass_fractions():
                state.set_mass_fractions(fractions)
            elif state.using_volu_fractions():
                state.set_volu_fractions(fractions)
            else:
                state.set_mole_fractions(fractions)
        handle = _StateHandle(state)
        states[fluid] = handle
        if len(states) > _MAX_STATES_PER_THREAD:
            states.popitem(last=False)
    states.move_to_end(fluid)
    return handle


def _updated_state(input_1, value_1, input_2, value_2, refrigerant):
    value_1, value_2 = float(value_1), float(value_2)
    if not math.isfinite(value_1) or not math.isfinite(value_2):
        raise ValueError("CoolProp state inputs must be finite.")
    pair, first, second = generate_update_pair(
        _parameter_index(input_1), value_1, _parameter_index(input_2), value_2)
    handle = _state_handle(refrigerant)
    inputs = (pair, first, second)
    if handle.last_inputs != inputs:
        # A failed update may mutate the backend. Never retain the previous
        # successful key after attempting another state, even if it fails.
        handle.last_inputs = None
        handle.state.update(pair, first, second)
        handle.last_inputs = inputs
    return handle.state


def to_kelvin(temperature_C: float) -> float:
    return temperature_C + KELVIN_OFFSET


def to_celsius(temperature_K: float) -> float:
    return temperature_K - KELVIN_OFFSET


def resolve_refrigerant(refrigerant: str) -> str:
    """Converte nomes de projeto em identificadores aceitos pelo CoolProp."""
    return REFRIGERANT_ALIASES.get(refrigerant.strip().upper(), refrigerant)


@lru_cache(maxsize=200_000)
def props_si_cached(
    output: str,
    input_1: str,
    value_1: float,
    input_2: str,
    value_2: float,
    refrigerant: str,
) -> float:
    """Read one property without reconstructing the backend or repeating a flash."""
    state = _updated_state(input_1, value_1, input_2, value_2, refrigerant)
    return state.keyed_output(_parameter_index(output))


@lru_cache(maxsize=100_000)
def state_properties_cached(input_1, value_1, input_2, value_2, refrigerant):
    """Return (T [K], h [J/kg], s [J/(kg K)], Q) after a single state update.

    Quality is informational outside the two-phase region; its raw sentinel
    is normalized by ThermodynamicState, not used to impose a phase here.
    """
    state = _updated_state(input_1, value_1, input_2, value_2, refrigerant)
    try:
        quality = state.Q()
    except ValueError:
        quality = float("nan")
    return state.T(), state.hmass(), state.smass(), quality


@lru_cache(maxsize=128)
def props_si_constant_cached(output: str, refrigerant: str) -> float:
    return _state_handle(refrigerant).state.trivial_keyed_output(_parameter_index(output))


def clear_property_caches():
    """Clear immutable caches and this thread's mutable backend pool.

    Intended for tests/diagnostics between calculations, not during a solve.
    """
    for function in (props_si_cached, state_properties_cached,
                     props_si_constant_cached, _parameter_index):
        function.cache_clear()
    if hasattr(_STATE_POOL, "states"):
        _STATE_POOL.states.clear()


def saturation_pressure_Pa(
    refrigerant: str,
    temperature_C: float,
    quality: float = 0.0,
) -> float:
    return props_si_cached(
        "P",
        "T",
        to_kelvin(temperature_C),
        "Q",
        quality,
        refrigerant,
    )


def critical_temperature_C(refrigerant: str) -> float:
    return to_celsius(props_si_constant_cached("Tcrit", refrigerant))

