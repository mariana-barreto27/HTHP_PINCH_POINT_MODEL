"""COP-map palette and drawing helpers shared by the analyses."""

from matplotlib.colors import LinearSegmentedColormap

from hthp.plots.style import add_minor_grid

COP_CMAP = LinearSegmentedColormap.from_list(
    "hthp_cop",
    ["#00A6E0", "#B23A90", "#F5333F"],
)
COP_CMAP.set_bad("#EDE7DF")


def heatmap(ax, X, Y, values, *, cbar_label, levels):
    # The raster layer gives invalid states an explicit pale fill; contourf
    # alone leaves masked cells transparent, exposing gridlines in infeasible
    # regions. The contour layer smooths the visual transitions between the
    # actually calculated grid points without changing their values.
    surface = ax.pcolormesh(X, Y, values, shading="auto", cmap=COP_CMAP,
                            vmin=levels[0], vmax=levels[-1], rasterized=True)
    ax.contourf(X, Y, values, levels=levels, cmap=COP_CMAP,
                vmin=levels[0], vmax=levels[-1], corner_mask=False,
                antialiased=True)
    add_minor_grid(ax)
    colorbar = ax.figure.colorbar(surface, ax=ax, label=cbar_label)
    return surface, colorbar
