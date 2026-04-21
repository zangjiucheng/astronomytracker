"""
status_tab.py

Defines the ``StatusTab`` widget used in the astronomy tracker UI.  The
status tab presents real‑time information about the target's current
ephemeris, including whether it is observable, the observation
quality score, basic astronomical coordinates and a summary of the
weather conditions.  Breaking the status card out into its own tab
allows the user to quickly check on the current state without being
overwhelmed by plots or input controls.

This module mirrors the original status panel from the monolithic
``gui.py`` but encapsulates it in a reusable QWidget subclass.  The
tab attaches several widgets back onto the parent ``AstronomyTrackerWindow``
instance so that existing methods can still refer to attributes like
``indicator_dot``, ``value_labels`` and ``reasons_summary``.

"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class StatusTab(QWidget):
    """Widget displaying the current ephemeris and observation quality."""

    def __init__(self, window: "AstronomyTrackerWindow") -> None:
        super().__init__()
        # Store a reference to the parent window so we can attach widgets
        # back onto it.  The forward string annotation avoids a circular
        # import during runtime.
        self.window = window
        self._build_ui()

    def _build_ui(self) -> None:
        """Construct the status tab UI."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(12)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("statusScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(12)

        scroll_area.setWidget(scroll_content)

        # Status card summarising the latest ephemeris sample.
        status_card = QFrame()
        status_card.setObjectName("cardFrame")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(14, 14, 14, 14)
        status_layout.setSpacing(12)

        status_layout.addWidget(self.window._section_title("Current Ephemeris"))

        # Top row: coloured indicator dot and summarised visibility/score.
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        # Create the indicator dot on the parent window.  It will be
        # updated based on the latest observation score.
        self.window.indicator_dot = QLabel()
        self.window.indicator_dot.setFixedSize(16, 16)
        self.window.indicator_dot.setObjectName("indicatorDot")

        # Summary labels for visibility and score on the parent window.
        self.window.visibility_summary = QLabel("Not observable")
        self.window.visibility_summary.setObjectName("statusValueLabel")

        self.window.score_summary = QLabel("Score 0/100")
        self.window.score_summary.setObjectName("mutedLabel")

        self.window.status_detail = QLabel("Waiting for data")
        self.window.status_detail.setWordWrap(True)
        self.window.status_detail.setObjectName("mutedLabel")

        status_summary_layout = QVBoxLayout()
        status_summary_layout.setSpacing(3)
        status_summary_layout.addWidget(self.window.visibility_summary)
        status_summary_layout.addWidget(self.window.score_summary)
        status_summary_layout.addWidget(self.window.status_detail)

        top_row.addWidget(self.window.indicator_dot, 0, Qt.AlignmentFlag.AlignTop)
        top_row.addLayout(status_summary_layout)
        top_row.addStretch(1)
        status_layout.addLayout(top_row)

        # Grid of metric cards showing various numeric values.
        metrics_grid = QGridLayout()
        metrics_grid.setHorizontalSpacing(12)
        metrics_grid.setVerticalSpacing(12)

        # Dictionary on the parent window where individual metric labels
        # will be stored for easy reference when updating the display.
        self.window.value_labels = {}
        fields = [
            ("UTC Time", "utc_time"),
            ("Local Time", "local_time"),
            ("RA", "ra_deg"),
            ("Dec", "dec_deg"),
            ("Azimuth", "az_deg"),
            ("Elevation", "el_deg"),
            ("Solar Elongation", "solar_elong_deg"),
            ("Compass", "compass_direction"),
            ("Observation Score", "obs_score"),
            ("Observation Grade", "obs_grade"),
            ("Limiting Factor", "obs_limiting"),
            ("Cloud Cover", "weather_cloud"),
            ("Humidity", "weather_humidity"),
            ("Wind", "weather_wind"),
            ("Visibility", "weather_visibility"),
        ]

        for index, (label_text, key) in enumerate(fields):
            row = index // 3
            col = index % 3
            card, value_label = self.window._make_metric_card(label_text)
            # Store the value label in the parent window's dictionary so
            # other methods can update it by key.
            self.window.value_labels[key] = value_label
            metrics_grid.addWidget(card, row, col)

        status_layout.addLayout(metrics_grid)

        # Reasons summary explaining why the score is what it is.
        self.window.reasons_summary = QLabel("Reasons: waiting for data")
        self.window.reasons_summary.setObjectName("mutedLabel")
        self.window.reasons_summary.setWordWrap(True)
        status_layout.addWidget(self.window.reasons_summary)

        scroll_layout.addWidget(status_card)

        log_card = QFrame()
        log_card.setObjectName("cardFrame")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(14, 14, 14, 14)
        log_layout.setSpacing(12)
        log_layout.addWidget(self.window._section_title("Sample Log"))
        self.window.log_view = QPlainTextEdit()
        self.window.log_view.setReadOnly(True)
        self.window.log_view.setObjectName("logView")
        self.window.log_view.setMaximumBlockCount(0)
        self.window.log_view.setMinimumHeight(180)
        log_layout.addWidget(self.window.log_view)
        scroll_layout.addWidget(log_card, 1)
        outer_layout.addWidget(scroll_area, 1)
