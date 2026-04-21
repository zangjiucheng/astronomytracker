"""Controls tab for the astronomy tracker.

This module defines the :class:`ControlsTab` widget used by the
astronomy tracker user interface.  The controls tab groups all
user‑interactive widgets related to target selection, observer
location input, refresh timing and timeline navigation.  By moving
these widgets into their own tab, the overall interface becomes
easier to understand and less cluttered compared to a single pane
containing everything.

The tab attaches key widgets back onto the parent
:class:`~astronomy.gui.AstronomyTrackerWindow` instance so that
existing methods can continue to reference attributes like
``latitude_spin`` directly on the window.  This preserves backwards
compatibility with code that previously expected these attributes to
live on the main window.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QSlider,
    QPushButton,
)


class ControlsTab(QWidget):
    """Widget containing all controls for the astronomy tracker."""

    def __init__(self, window: "AstronomyTrackerWindow") -> None:
        super().__init__()
        self.window = window
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(10)

        target_name = QLabel(self.window.config.target_name)
        target_name.setObjectName("cardPrimaryLabel")
        display_command = (
            self.window.state.target_command.strip("'") or "(not configured)"
        )
        target_cmd = QLabel(display_command)
        target_cmd.setObjectName("mutedLabel")
        target_cmd.setStyleSheet("font-size: 10px;")

        self.window.latitude_spin = self.window._make_spinbox(-90.0, 90.0, 6, 43.2557)
        self.window.longitude_spin = self.window._make_spinbox(
            -360.0, 360.0, 6, -79.8711
        )
        self.window.elevation_spin = self.window._make_spinbox(-1.0, 10.0, 3, 0.10)
        self.window.interval_spin = self.window._make_spinbox(1.0, 3600.0, 0, 10.0)
        self.window.interval_spin.setSingleStep(1.0)
        self.window.interval_spin.setSuffix(" s")

        self.window.load_ip_button = QPushButton("IP")
        self.window.load_ip_button.setObjectName("secondaryButton")

        self.window.start_button = QPushButton("Start")
        self.window.start_button.setObjectName("primaryButton")
        self.window.stop_button = QPushButton("Stop")
        self.window.stop_button.setObjectName("dangerButton")
        self.window.stop_button.setEnabled(False)

        for w in [
            self.window.latitude_spin,
            self.window.longitude_spin,
            self.window.elevation_spin,
            self.window.interval_spin,
        ]:
            w.setMaximumWidth(90)
            w.setMinimumHeight(26)
            w.setStyleSheet(w.styleSheet() + "padding: 4px 6px;")

        for btn in [
            self.window.start_button,
            self.window.stop_button,
            self.window.load_ip_button,
        ]:
            btn.setMaximumWidth(60)
            btn.setMinimumHeight(26)

        row1.addWidget(target_name)
        row1.addWidget(target_cmd)
        row1.addSpacing(6)
        row1.addWidget(QLabel("Lat"))
        row1.addWidget(self.window.latitude_spin)
        row1.addWidget(QLabel("Lon"))
        row1.addWidget(self.window.longitude_spin)
        row1.addWidget(QLabel("Elev"))
        row1.addWidget(self.window.elevation_spin)
        row1.addSpacing(6)
        row1.addWidget(QLabel("Int"))
        row1.addWidget(self.window.interval_spin)
        row1.addSpacing(6)
        row1.addWidget(self.window.load_ip_button)
        row1.addWidget(self.window.start_button)
        row1.addWidget(self.window.stop_button)
        row1.addStretch(1)
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)

        self.window.timeline_status_label = QLabel("LIVE")
        self.window.timeline_status_label.setObjectName("timelineBadge")
        self.window.timeline_status_label.setFixedSize(120, 26)
        self.window.timeline_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.window.timeline_status_label.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )

        self.window.timeline_slider = QSlider(Qt.Orientation.Horizontal)
        self.window.timeline_slider.setRange(0, self.window.prediction_horizon_minutes)
        self.window.timeline_slider.setValue(0)
        self.window.timeline_slider.setSingleStep(1)
        self.window.timeline_slider.setPageStep(10)
        self.window.timeline_slider.setEnabled(True)

        self.window.back_to_live_button = QPushButton("Back to live")
        self.window.back_to_live_button.setObjectName("ghostButton")
        self.window.back_to_live_button.setEnabled(False)

        row2.addWidget(self.window.timeline_status_label)
        row2.addWidget(self.window.timeline_slider, 1)
        row2.addWidget(self.window.back_to_live_button)
        outer.addLayout(row2)
