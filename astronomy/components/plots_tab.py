from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QPushButton, QSplitter, QVBoxLayout, QWidget


class PlotsTab(QWidget):
    """Widget containing sky projection and time-series plots."""

    def __init__(self, window: "AstronomyTrackerWindow") -> None:
        super().__init__()
        self.window = window
        self._build_ui()

    def _build_ui(self) -> None:
        if not hasattr(self.window, "sky_plot"):
            self.window._init_sky_projection_plot()

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(10)

        chart_log_splitter = QSplitter(Qt.Orientation.Vertical)
        chart_log_splitter.setObjectName("chartLogSplitter")
        chart_log_splitter.setChildrenCollapsible(False)

        plot_card = QFrame()
        plot_card.setObjectName("cardFrame")
        plot_layout = QVBoxLayout(plot_card)
        plot_layout.setContentsMargins(18, 18, 18, 18)
        plot_layout.setSpacing(12)

        header_row = QVBoxLayout()
        header_row.setSpacing(4)

        sky_title = self.window._section_title("Sky Projection (Alt-Az)")
        reset_sky_btn = QPushButton("Reset")
        reset_sky_btn.setObjectName("ghostButton")
        reset_sky_btn.setMaximumWidth(50)
        reset_sky_btn.clicked.connect(self._reset_sky)
        sky_title_h = QVBoxLayout()
        sky_title_h.addWidget(sky_title)
        sky_title_h.addWidget(reset_sky_btn)
        sky_title_h.addStretch(1)
        plot_layout.addLayout(sky_title_h)

        plot_layout.addWidget(self.window.sky_plot)
        plot_layout.addWidget(self.window._section_title("Live Plot"))

        reset_all_btn = QPushButton("Reset All Plots")
        reset_all_btn.setObjectName("ghostButton")
        reset_all_btn.clicked.connect(self._reset_all_plots)
        plot_layout.addWidget(reset_all_btn, 0, Qt.AlignmentFlag.AlignRight)

        plot_layout.addWidget(self.window.elevation_plot)
        plot_layout.addWidget(self.window.azimuth_plot)
        plot_layout.addWidget(self.window.score_plot)
        plot_layout.addWidget(self.window.weather_plot)

        chart_log_splitter.addWidget(plot_card)

        outer_layout.addWidget(chart_log_splitter, 1)

    def _reset_sky(self) -> None:
        self.window.sky_plot.setXRange(-1.1, 1.1)
        self.window.sky_plot.setYRange(-1.1, 1.1)

    def _reset_all_plots(self) -> None:
        self.window.elevation_plot.setYRange(-90.0, 90.0)
        self.window.elevation_plot.enableAutoRange(x=True, y=False)
        self.window.azimuth_plot.setYRange(0.0, 360.0)
        self.window.azimuth_plot.enableAutoRange(x=True, y=False)
        self.window.score_plot.setYRange(0.0, 100.0)
        self.window.score_plot.enableAutoRange(x=True, y=False)
        self.window.weather_plot.setYRange(0.0, 100.0)
        self.window.weather_plot.enableAutoRange(x=True, y=False)
