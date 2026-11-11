"""Shared look for all plots: thin lines, quiet grid, text in ink colours (never the data colour)."""
import matplotlib.pyplot as plt

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

# One colour per ENTITY, the same in every chart.
COLORS = {
    "Reno": "#2a78d6",          # blue
    "CUBIC": "#eb6834",         # orange
    "Fixed window 8": "#1baf7a",    # aqua
    "Fixed window 64": "#eda100",   # yellow
    "flow 1": "#2a78d6",
    "flow 2": "#eb6834",
}
BLUE, ORANGE = COLORS["Reno"], COLORS["CUBIC"]


def apply():
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "text.color": INK,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 1,
        "axes.axisbelow": True, "axes.titlelocation": "left", "axes.titlesize": 12,
        "axes.titlecolor": INK, "font.size": 10.5,
        "lines.linewidth": 2, "lines.solid_capstyle": "round", "lines.solid_joinstyle": "round",
        "legend.frameon": False, "legend.labelcolor": INK2,
    })
