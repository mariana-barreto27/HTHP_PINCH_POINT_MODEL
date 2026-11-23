"""Large paired comparisons must keep every legend entry clear of the axis label."""

import unittest
from unittest.mock import patch

from hthp.analyses import plot_curves
from hthp.comparisons import comparison_views
from hthp.configurations import ARCHITECTURES, ComponentParams


class PairedPlotLayoutTests(unittest.TestCase):
    def test_twenty_five_architecture_legend_does_not_overlap_axis_title(self):
        groups = [(label, [dict(configuration=label, status="valid", COP=2.0,
                                low_condensation_C=t) for t in (30, 60)])
                  for label, _, _ in ARCHITECTURES]

        def check(fig, path):
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            ax = fig.axes[0]
            legend_box = ax.get_legend().get_window_extent(renderer)
            label_box = ax.xaxis.label.get_window_extent(renderer)
            self.assertGreaterEqual(label_box.y0 - legend_box.y1, 4)
            self.assertEqual(len(ax.get_legend().get_texts()), len(ARCHITECTURES))

        with patch("hthp.analyses.save_figure", side_effect=check):
            plot_curves(groups, "low_condensation_C", "COP",
                        "Low-stage condensation temperature [°C]", "Overall COP [-]",
                        "Synthetic layout test only", "not-saved", ComponentParams())

    def test_twenty_and_fifty_labels_do_not_overlap_the_x_axis_title(self):
        for cases in (comparison_views("expansor")[0].cases, ARCHITECTURES):
            with self.subTest(labels=2 * len(cases)):
                groups = []
                for enabled in (False, True):
                    for label, _, _ in cases:
                        name = label + (" + subcooler" if enabled else " (no subcooler)")
                        rows = [dict(configuration=name, base_configuration=label,
                                     status="valid", with_high_stage_subcooler=enabled,
                                     low_condensation_C=t, COP=2.0) for t in (30, 60)]
                        groups.append((name, rows))

                def check(fig, path):
                    fig.canvas.draw()
                    renderer = fig.canvas.get_renderer()
                    ax = fig.axes[0]
                    legend = ax.get_legend()
                    legend_box = legend.get_window_extent(renderer)
                    label_box = ax.xaxis.label.get_window_extent(renderer)
                    self.assertGreaterEqual(label_box.y0 - legend_box.y1, 4)
                    self.assertEqual(len(legend.get_texts()), len(groups))
                    self.assertGreater(ax.get_window_extent(renderer).height, 100)

                with patch("hthp.analyses.save_figure", side_effect=check):
                    plot_curves(groups, "low_condensation_C", "COP",
                                "Low-stage condensation temperature [°C]", "Overall COP [-]",
                                "Synthetic layout test only", "not-saved", ComponentParams(),
                                subcooler_comparison=True)


if __name__ == "__main__":
    unittest.main()
