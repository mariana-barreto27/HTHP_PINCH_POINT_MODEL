"""Matplotlib figure helpers using the shared HP-DAC house style."""

from hthp.plots.style import MM  # importing style applies the shared rcParams
import matplotlib.pyplot as plt


def create_figure():
    fig, ax = plt.subplots(figsize=(190 * MM, 120 * MM))
    return fig, ax
