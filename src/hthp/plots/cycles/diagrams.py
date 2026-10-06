"""Combined cascade diagrams styled after HP-DAC/utils/Plots."""

import numpy as np
from CoolProp.CoolProp import PropsSI
from matplotlib.ticker import LogLocator, NullFormatter

from hthp.plots.figures import create_figure
from hthp.plots.style import add_minor_grid

STAGE_COLORS = {"low": "#14304A", "high": "#8C3A26"}


def _coordinates(cycle, diagram):
    pressure = np.asarray(cycle["P_bar"], dtype=float)
    enthalpy = np.asarray(cycle["H_J_kg"], dtype=float)
    if diagram == "Ph":
        return enthalpy / 1000, pressure
    entropy = np.array([PropsSI("S", "P", p * 1e5, "H", h, cycle["fluid"])
                        for p, h in zip(pressure, enthalpy)]) / 1000
    temperature = np.array([PropsSI("T", "P", p * 1e5, "H", h, cycle["fluid"])
                            for p, h in zip(pressure, enthalpy)]) - 273.15
    return entropy, temperature


def _saturation(ax, fluid, color, diagram, pressure_min, pressure_max):
    """Draw liquid/vapour saturation boundaries with the reference dotted line."""
    p_triple = float(PropsSI("PTRIPLE", fluid))
    p_critical = float(PropsSI("PCRIT", fluid))
    # Show the complete subcritical dome, not just the operating-pressure band.
    # This is a visual reference only; the plotted cycle states stay unchanged.
    lower = max(p_triple * 1.001, min(0.8e5, pressure_min * 0.5))
    upper = p_critical * 0.999
    if upper <= lower:
        return [], []
    pressures = np.geomspace(lower, upper, 260)
    all_x, all_y = [], []
    for quality in (0, 1):
        xs, ys = [], []
        for pressure in pressures:
            try:
                enthalpy = PropsSI("H", "P", pressure, "Q", quality, fluid)
                if diagram == "Ph":
                    xs.append(enthalpy / 1000)
                    ys.append(pressure / 1e5)
                else:
                    xs.append(PropsSI("S", "P", pressure, "Q", quality, fluid) / 1000)
                    ys.append(PropsSI("T", "P", pressure, "Q", quality, fluid) - 273.15)
            except ValueError:
                xs.append(np.nan)
                ys.append(np.nan)
        ax.plot(xs, ys, color=color, linestyle=":", linewidth=1.15,
                alpha=0.88, marker="none", label="_nolegend_", zorder=1)
        all_x.extend(value for value in xs if np.isfinite(value))
        all_y.extend(value for value in ys if np.isfinite(value))
    return all_x, all_y


def _arrow(ax, x0, y0, x1, y1, color, logarithmic_y):
    """Place a restrained direction arrow near the middle of a process line."""
    f0, f1 = 0.43, 0.57
    if logarithmic_y and y0 > 0 and y1 > 0:
        ly0, ly1 = np.log(y0), np.log(y1)
        ya = np.exp(ly0 + f0 * (ly1 - ly0))
        yb = np.exp(ly0 + f1 * (ly1 - ly0))
    else:
        ya = y0 + f0 * (y1 - y0)
        yb = y0 + f1 * (y1 - y0)
    xa, xb = x0 + f0 * (x1 - x0), x0 + f1 * (x1 - x0)
    ax.annotate("", xy=(xb, yb), xytext=(xa, ya), zorder=4,
                arrowprops=dict(arrowstyle="-|>", color=color, lw=0,
                                mutation_scale=12))


def _label_states(ax, all_points):
    """Mark state points and place numbered circular callouts around clusters."""
    ax.figure.canvas.draw()
    placed = []
    directions = np.linspace(0, 2 * np.pi, 16, endpoint=False)
    for points, labels, color in all_points:
        xy_pixels = ax.transData.transform(points)
        center = xy_pixels.mean(axis=0)
        for point, pixel, label in zip(points, xy_pixels, labels):
            dx, dy = pixel - center
            preferred = np.arctan2(dy, dx)
            angles = preferred + directions
            offsets = [(13 * np.cos(a), 13 * np.sin(a)) for a in angles]
            def clearance(offset):
                target = pixel + np.asarray(offset) * ax.figure.dpi / 72
                return min((np.linalg.norm(target - prior) for prior in placed),
                           default=100.0)
            offset = max(offsets, key=clearance)
            placed.append(pixel + np.asarray(offset) * ax.figure.dpi / 72)
            ax.annotate(str(label), xy=point, xytext=offset, textcoords="offset points",
                        ha="center", va="center", fontsize=9, fontweight="bold",
                        color=color, annotation_clip=False, zorder=7,
                        bbox=dict(boxstyle="circle,pad=0.32", facecolor="white",
                                  edgecolor=color, linewidth=1.15))


def plot_cycles(cycles, diagram, ax=None):
    """Plot both cascade stages together without changing calculated states."""
    if diagram not in ("Ph", "Ts"):
        raise ValueError("Supported diagrams: Ph, Ts.")
    if ax is None:
        fig, ax = create_figure()
    else:
        fig = ax.figure

    state_callouts = []
    handles, labels_for_legend = [], []
    saturation_x, saturation_y = [], []
    for cycle in cycles:
        stage = cycle.get("stage", "low")
        color = STAGE_COLORS.get(stage, "#14304A")
        x, y = _coordinates(cycle, diagram)
        stage_title = "Low stage" if stage == "low" else "High stage"
        handle, = ax.plot([], [], color=color, linewidth=2.3, marker="none",
                          linestyle="-", label=f"{stage_title} — {cycle['fluid']}")
        handles.append(handle)
        labels_for_legend.append(f"{stage_title} — {cycle['fluid']}")
        sx, sy = _saturation(ax, cycle["fluid"], color, diagram,
                             float(np.min(cycle["P_bar"])) * 1e5,
                             float(np.max(cycle["P_bar"])) * 1e5)
        saturation_x.extend(sx)
        saturation_y.extend(sy)

        fill_indices = cycle.get("fill_indices")
        if fill_indices:
            polygon_x, polygon_y = x[fill_indices], y[fill_indices]
        elif not cycle.get("connections"):
            polygon_x, polygon_y = x, y
        else:
            polygon_x = polygon_y = None
        if polygon_x is not None:
            ax.fill(polygon_x, polygon_y, color=color, alpha=0.13,
                    linewidth=0, zorder=2)

        connections = cycle.get("connections")
        if connections:
            for start, end, line_style in connections:
                ax.plot([x[start], x[end]], [y[start], y[end]],
                        color=color, linestyle=line_style, linewidth=2.2,
                        marker="none", zorder=3)
                if line_style == "-":
                    _arrow(ax, x[start], y[start], x[end], y[end], color,
                           logarithmic_y=(diagram == "Ph"))
        else:
            ax.plot(np.r_[x, x[0]], np.r_[y, y[0]], color=color,
                    linestyle="-", linewidth=2.2, marker="none", zorder=3)
            for i in range(len(x)):
                j = (i + 1) % len(x)
                _arrow(ax, x[i], y[i], x[j], y[j], color, diagram == "Ph")

        point_labels = cycle.get("point_labels", [str(i) for i in range(1, len(x) + 1)])
        unique = {}
        for point, point_label in zip(np.column_stack((x, y)), point_labels):
            key = (round(float(point[0]), 8), round(float(point[1]), 8))
            unique.setdefault(key, (point, point_label))
        unique_points = [entry[0] for entry in unique.values()]
        unique_labels = [entry[1] for entry in unique.values()]
        unique_points = np.asarray(unique_points)
        ax.plot(unique_points[:, 0], unique_points[:, 1], linestyle="none", marker="o",
                markersize=5.0, markerfacecolor="white", markeredgecolor=color,
                markeredgewidth=1.2, zorder=6)
        state_callouts.append((unique_points, unique_labels, color))

    if diagram == "Ph":
        ax.set_yscale("log")
        ax.set_xlabel("Specific enthalpy [kJ kg$^{-1}$]")
        ax.set_ylabel("Pressure [bar]")
        enthalpies = np.concatenate([np.asarray(c["H_J_kg"], dtype=float) / 1000 for c in cycles])
        pressures = np.concatenate([np.asarray(c["P_bar"], dtype=float) for c in cycles])
        h_span = max(float(np.ptp(enthalpies)), 1.0)
        h_min = min(float(enthalpies.min()), min(saturation_x, default=float(enthalpies.min())))
        h_max = max(float(enthalpies.max()), max(saturation_x, default=float(enthalpies.max())))
        ax.set_xlim(h_min - 0.03 * h_span, h_max + 0.06 * h_span)
        ax.set_ylim(min(0.8, float(pressures.min()) * 0.42),
                    max(float(pressures.max()) * 2.8, max(saturation_y, default=0.0) * 1.05))
        ax.yaxis.set_major_locator(LogLocator(base=10))
        ax.yaxis.set_minor_locator(LogLocator(base=10, subs=np.arange(2, 10) * 0.1))
        ax.yaxis.set_minor_formatter(NullFormatter())
    else:
        ax.set_xlabel("Specific entropy [kJ kg$^{-1}$ K$^{-1}$]")
        ax.set_ylabel("Temperature [°C]")

    ax.grid(True, which="major", linestyle="--", linewidth=0.6, color="black")
    add_minor_grid(ax)
    _label_states(ax, state_callouts)
    ax.legend(handles, labels_for_legend, loc="upper center",
              bbox_to_anchor=(0.5, -0.17), ncols=2, fontsize=10)
    return fig, ax
