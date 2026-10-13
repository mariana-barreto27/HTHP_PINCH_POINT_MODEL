"""Shared plotting style recovered from HP-DAC/utils/Plots."""

import matplotlib as mpl
import matplotlib.pyplot as plt
from cycler import cycler

COLORS = ("#14304A", "#6C8FA8", "#8C3A26", "#3A6EA5",
          "#2C3E4C", "#A39A6B", "#767676", "#000000", "#447B65", "#7A568C")
MARKERS = ("o", "s", "^", "D", "v", "P", "X", "*", "<", ">")
DASHES = ("-", "--", "-.", ":", (0, (5, 1, 1, 1)),
          (0, (3, 1, 3, 1)), (0, (1, 1)), (0, (7, 2)),
          (0, (5, 2, 1, 2)), (0, (2, 2, 6, 2)))
MM = 1 / 25.4

plt.rcParams.update({
    "axes.prop_cycle": cycler(color=COLORS) + cycler(marker=MARKERS) + cycler(linestyle=DASHES),
    "lines.markeredgecolor": "black", "lines.markeredgewidth": 1.0,
    "lines.markersize": 7.0, "lines.linewidth": 1.8,
    "scatter.edgecolors": "black", "errorbar.capsize": 3.0,
    "patch.force_edgecolor": True, "patch.edgecolor": "white", "patch.linewidth": 0.8,
    "font.family": "serif", "font.serif": ["Latin Modern Roman", "CMU Serif", "DejaVu Serif"],
    "mathtext.fontset": "cm", "mathtext.default": "regular",
    "font.size": 11, "axes.labelsize": 13, "axes.titlesize": 13,
    "xtick.labelsize": 12, "ytick.labelsize": 12, "legend.fontsize": 12,
    "axes.linewidth": 1.4, "axes.edgecolor": "black",
    "axes.labelpad": 8.0, "axes.titlepad": 10.0, "axes.axisbelow": True,
    "axes.formatter.use_mathtext": True, "axes.formatter.limits": (-3, 4),
    "axes.xmargin": 0.06, "axes.ymargin": 0.09,
    "savefig.pad_inches": 0.08, "figure.constrained_layout.use": True,
    "figure.constrained_layout.h_pad": 0.06, "figure.constrained_layout.w_pad": 0.06,
    "axes.grid": True, "axes.grid.which": "major", "grid.color": "black",
    "grid.linestyle": "--", "grid.linewidth": 0.6, "grid.alpha": 1.0,
    "xtick.direction": "in", "ytick.direction": "in", "xtick.top": True,
    "ytick.right": True, "xtick.minor.visible": True, "ytick.minor.visible": True,
    "xtick.major.size": 6.0, "ytick.major.size": 6.0,
    "xtick.minor.size": 3.0, "ytick.minor.size": 3.0,
    "xtick.major.width": 1.2, "ytick.major.width": 1.2,
    "xtick.minor.width": 0.8, "ytick.minor.width": 0.8,
    "xtick.major.pad": 6.0, "ytick.major.pad": 6.0,
    "legend.frameon": True, "legend.framealpha": 1.0,
    "legend.edgecolor": "0.6", "legend.fancybox": False,
    "legend.borderpad": 0.5, "legend.labelspacing": 0.5,
    "legend.borderaxespad": 0.8, "legend.numpoints": 1,
    "legend.scatterpoints": 1,
    "figure.figsize": (190 * MM, 120 * MM), "figure.dpi": 150,
    "figure.facecolor": "white", "savefig.dpi": 600,
    "savefig.bbox": "tight", "pdf.fonttype": 42, "ps.fonttype": 42,
    "svg.fonttype": "none",
})


def add_minor_grid(ax):
    """Apply the standard light dotted minor grid to one axes."""
    ax.grid(True, which="minor", linestyle=":", linewidth=0.4, color="gray")


def save_figure(fig, path):
    """Save the standard high-resolution PNG and vector PDF pair."""
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path.with_suffix(".png"), bbox_inches="tight")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight")
