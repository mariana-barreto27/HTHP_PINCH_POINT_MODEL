"""Padrão visual HpDAC compartilhado por todas as análises."""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from cycler import cycler
from matplotlib.colors import LinearSegmentedColormap


COLORS = [
    "#14304A",
    "#6C8FA8",
    "#8C3A26",
    "#3A6EA5",
    "#2C3E4C",
    "#A39A6B",
    "#767676",
    "#000000",
]
MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*"]
DASHES = [
    "-",
    "--",
    "-.",
    ":",
    (0, (5, 1, 1, 1)),
    (0, (3, 1, 3, 1)),
    (0, (1, 1)),
    (0, (7, 2)),
]
MM = 1.0 / 25.4

HOUSE_DIVERGING = LinearSegmentedColormap.from_list(
    "house_diverging",
    ["#00A6E0", "#B23A90", "#F5333F"],
)
HOUSE_DIVERGING.set_bad("#EDE7DF")


def apply_plot_standard() -> None:
    """Aplica o padrão do notebook de referência a uma sessão Matplotlib."""
    plt.rcParams.update(
        {
            "axes.prop_cycle": (
                cycler(color=COLORS)
                + cycler(marker=MARKERS)
                + cycler(linestyle=DASHES)
            ),
            "font.family": "serif",
            "font.serif": [
                "Latin Modern Roman",
                "CMU Serif",
                "DejaVu Serif",
            ],
            "mathtext.fontset": "cm",
            "mathtext.default": "regular",
            "font.size": 11,
            "axes.labelsize": 13,
            "axes.titlesize": 13,
            "xtick.labelsize": 12,
            "ytick.labelsize": 12,
            "legend.fontsize": 9,
            "axes.linewidth": 1.4,
            "axes.edgecolor": "black",
            "axes.labelpad": 8,
            "axes.titlepad": 10,
            "axes.axisbelow": True,
            "axes.formatter.use_mathtext": True,
            "axes.formatter.limits": (-3, 4),
            "axes.grid": True,
            "grid.color": "black",
            "grid.linestyle": "--",
            "grid.linewidth": 0.6,
            "grid.alpha": 1.0,
            "xtick.direction": "in",
            "ytick.direction": "in",
            "xtick.top": True,
            "ytick.right": True,
            "xtick.minor.visible": True,
            "ytick.minor.visible": True,
            "xtick.major.size": 6,
            "ytick.major.size": 6,
            "xtick.major.width": 1.2,
            "ytick.major.width": 1.2,
            "xtick.minor.size": 3,
            "ytick.minor.size": 3,
            "xtick.minor.width": 0.8,
            "ytick.minor.width": 0.8,
            "xtick.major.pad": 6,
            "ytick.major.pad": 6,
            "lines.linewidth": 1.8,
            "lines.markersize": 7,
            "lines.markeredgecolor": "black",
            "lines.markeredgewidth": 1.0,
            "scatter.edgecolors": "black",
            "errorbar.capsize": 3,
            "patch.edgecolor": "white",
            "legend.frameon": True,
            "legend.framealpha": 1.0,
            "legend.edgecolor": "black",
            "legend.fancybox": False,
            "legend.borderpad": 0.5,
            "legend.numpoints": 1,
            "figure.figsize": (190 * MM, 120 * MM),
            "figure.dpi": 150,
            "figure.facecolor": "white",
            "figure.constrained_layout.use": True,
            "figure.constrained_layout.h_pad": 0.06,
            "figure.constrained_layout.w_pad": 0.06,
            "axes.xmargin": 0.06,
            "axes.ymargin": 0.09,
            "savefig.dpi": 600,
            "savefig.bbox": "tight",
            "savefig.facecolor": "white",
            "pdf.fonttype": 42,
            "svg.fonttype": "none",
        }
    )


def finish_axis(axis: mpl.axes.Axes) -> None:
    """Acrescenta a grade menor pontilhada definida pelo padrão."""
    axis.grid(True, which="major", color="black", linestyle="--", linewidth=0.6)
    axis.grid(True, which="minor", color="gray", linestyle=":", linewidth=0.4)


def save_standard_figure(
    figure: mpl.figure.Figure,
    path: Path,
    dpi: int = 600,
) -> tuple[Path, Path]:
    """Exporta a mesma figura em PNG de alta resolução e PDF vetorial."""
    png_path = path.with_suffix(".png")
    pdf_path = path.with_suffix(".pdf")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(png_path, dpi=dpi, bbox_inches="tight", facecolor="white")
    figure.savefig(pdf_path, bbox_inches="tight", facecolor="white")
    return png_path, pdf_path
