"""State-data adapters for the optional diagrams in the reference."""

from .diagrams import plot_cycles


def make_cycle(fluid, pressures, enthalpies, *, stage):
    if len(pressures) != len(enthalpies):
        raise ValueError("Pressure and enthalpy arrays must have equal length.")
    return {"fluid": fluid, "P_bar": list(pressures),
            "H_J_kg": list(enthalpies), "stage": stage}


def plot_ph(cycles):
    return plot_cycles(cycles, "Ph")


def plot_ts(cycles):
    return plot_cycles(cycles, "Ts")
