from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pyqtgraph as pg
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QFont, QIcon, QPainter, QPainterPath, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFrame,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSlider,
    QSplitter,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from astronomy.api_fetcher import HorizonsFetcher
from astronomy.tracker_state import EphemerisSample, ObserverLocation, TrackerState, format_local_time

pg.setConfigOptions(antialias=True)


@dataclass(frozen=True)
class TrackerAppConfig:
    app_name: str = "Astronomy Tracker"
    organization_name: str = "Astronomy"
    window_title: str = "Astronomy Tracker"
    header_title: str = "Real-Time Astronomy Tracker"
    header_subtitle: str = (
        "PySide6 desktop tracker with live JPL Horizons sampling, historical log, and azimuth/elevation plot."
    )
    target_name: str = "Target"


class RequestThread(QThread):
    result_ready = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, action: Callable[[], object], parent: QObject | None = None):
        super().__init__(parent)
        self._action = action

    def run(self) -> None:
        try:
            result = self._action()
        except Exception as exc:  # noqa: BLE001
            self.error_occurred.emit(str(exc))
            return
        self.result_ready.emit(result)


class TrackingThread(QThread):
    sample_ready = Signal(object)
    error_occurred = Signal(str)
    status_message = Signal(str)

    def __init__(self, fetcher: HorizonsFetcher, state: TrackerState, parent: QObject | None = None):
        super().__init__(parent)
        self._fetcher = fetcher
        self._state_snapshot = state
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def update_state(self, state: TrackerState) -> None:
        with self._lock:
            self._state_snapshot = state

    def request_stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        self.status_message.emit("Tracking started")
        while not self._stop_event.is_set():
            with self._lock:
                state = self._state_snapshot

            try:
                sample = self._fetcher.fetch_current_ephemeris(state.target_command, state.location)
                self.sample_ready.emit(sample)
            except Exception as exc:  # noqa: BLE001
                self.error_occurred.emit(str(exc))

            interval = max(1, int(state.refresh_interval_sec))
            if self._stop_event.wait(interval):
                break

        self.status_message.emit("Tracking stopped")


class AstronomyTrackerWindow(QMainWindow):
    def __init__(
        self,
        state: TrackerState | None = None,
        config: TrackerAppConfig | None = None,
    ) -> None:
        super().__init__()
        self.fetcher = HorizonsFetcher()
        self.state = state or TrackerState()
        self.config = config or TrackerAppConfig()
        self.history_limit = 400
        self.plot_limit = 180
        self.log_lines: deque[str] = deque(maxlen=self.history_limit)
        self.timestamps: deque[float] = deque(maxlen=self.plot_limit)
        self.azimuths: deque[float] = deque(maxlen=self.plot_limit)
        self.elevations: deque[float] = deque(maxlen=self.plot_limit)
        self.prediction_horizon_minutes = 24 * 60
        self.prediction_step_minutes = 1
        self.prediction_refresh_seconds = 300
        self.follow_live_projection = True
        self.predicted_samples: list[EphemerisSample] = []
        self.last_prediction_anchor_utc: datetime | None = None
        self.tracking_thread: TrackingThread | None = None
        self.pending_request_thread: RequestThread | None = None
        self.prediction_request_thread: RequestThread | None = None

        self.setWindowTitle(self.config.window_title)
        self.resize(1320, 860)
        self._build_ui()
        self._apply_dark_theme()
        self._bind_signals()
        self._sync_controls_from_state()
        self._update_status_banner("Ready. Enter coordinates or use IP location, then start tracking.")

    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("rootWidget")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("heroFrame")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(14)

        title_stack = QVBoxLayout()
        title_stack.setSpacing(5)

        title = QLabel(self.config.header_title)
        title.setObjectName("titleLabel")
        title.setFont(QFont("Avenir Next", 21, QFont.Weight.Bold))

        subtitle = QLabel(self.config.header_subtitle)
        subtitle.setObjectName("subtitleLabel")
        subtitle.setWordWrap(True)

        self.header_badge = QLabel("JPL Horizons · Live")
        self.header_badge.setObjectName("headerBadge")
        self.header_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)

        badge_column = QVBoxLayout()
        badge_column.addStretch(1)
        badge_column.addWidget(self.header_badge, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        badge_column.addStretch(1)

        header_layout.addLayout(title_stack, 1)
        header_layout.addLayout(badge_column)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("mainSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)

        controls_panel = self._build_controls_panel()
        display_panel = self._build_display_panel()
        controls_scroll = self._build_scroll_container(controls_panel, "controlsScrollArea")
        display_scroll = self._build_scroll_container(display_panel, "displayScrollArea")

        splitter.addWidget(controls_scroll)
        splitter.addWidget(display_scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 1000])

        main_layout.addWidget(header)
        main_layout.addWidget(splitter, 1)

        self.statusBar().showMessage("Ready")

    def _build_scroll_container(self, content: QWidget, object_name: str) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName(object_name)
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        return scroll

    def _build_controls_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("controlsPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        target_box = QFrame()
        target_box.setObjectName("cardFrame")
        target_layout = QVBoxLayout(target_box)
        target_layout.setContentsMargins(14, 14, 14, 14)
        target_layout.setSpacing(10)
        target_layout.addWidget(self._section_title("Target"))

        target_name = QLabel(self.config.target_name)
        target_name.setObjectName("cardPrimaryLabel")
        display_command = self.state.target_command.strip("'") or "(not configured)"
        target_command = QLabel(f"Horizons command: {display_command}")
        target_command.setObjectName("mutedLabel")
        target_command.setWordWrap(True)
        target_layout.addWidget(target_name)
        target_layout.addWidget(target_command)
        layout.addWidget(target_box)

        input_box = QFrame()
        input_box.setObjectName("cardFrame")
        input_layout = QVBoxLayout(input_box)
        input_layout.setContentsMargins(14, 14, 14, 14)
        input_layout.setSpacing(12)
        input_layout.addWidget(self._section_title("Observer Location"))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)

        self.latitude_spin = self._make_spinbox(-90.0, 90.0, 6, 43.2557)
        self.longitude_spin = self._make_spinbox(-360.0, 360.0, 6, -79.8711)
        self.elevation_spin = self._make_spinbox(-1.0, 10.0, 3, 0.10)
        self.interval_spin = self._make_spinbox(1.0, 3600.0, 0, 10.0)
        self.interval_spin.setSingleStep(1.0)
        self.interval_spin.setSuffix(" s")

        form.addRow("Latitude", self.latitude_spin)
        form.addRow("Longitude", self.longitude_spin)
        form.addRow("Observer Altitude (km)", self.elevation_spin)
        form.addRow("Refresh interval", self.interval_spin)
        input_layout.addLayout(form)

        timeline_box = QFrame()
        timeline_box.setObjectName("subCardFrame")
        timeline_layout = QVBoxLayout(timeline_box)
        timeline_layout.setContentsMargins(12, 12, 12, 12)
        timeline_layout.setSpacing(10)
        timeline_layout.addWidget(self._section_title("Projection Timeline", compact=True))

        self.timeline_status_label = QLabel("LIVE")
        self.timeline_status_label.setObjectName("timelineBadge")
        timeline_layout.addWidget(self.timeline_status_label, 0, Qt.AlignmentFlag.AlignLeft)

        self.timeline_slider = QSlider(Qt.Orientation.Horizontal)
        self.timeline_slider.setRange(0, self.prediction_horizon_minutes)
        self.timeline_slider.setValue(0)
        self.timeline_slider.setSingleStep(1)
        self.timeline_slider.setPageStep(10)
        self.timeline_slider.setEnabled(True)
        timeline_layout.addWidget(self.timeline_slider)

        self.back_to_live_button = QPushButton("Back to live")
        self.back_to_live_button.setObjectName("ghostButton")
        self.back_to_live_button.setEnabled(False)
        timeline_layout.addWidget(self.back_to_live_button)

        input_layout.addWidget(timeline_box)

        self.load_ip_button = QPushButton("Use IP Location")
        self.load_ip_button.setObjectName("secondaryButton")
        self.start_button = QPushButton("Start Tracking")
        self.start_button.setObjectName("primaryButton")
        self.stop_button = QPushButton("Stop Tracking")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.setEnabled(False)

        input_layout.addWidget(self.load_ip_button)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)
        input_layout.addLayout(button_row)

        help_label = QLabel(
            "Tip: use the IP lookup to prefill coordinates, or enter your own observatory location."
        )
        help_label.setWordWrap(True)
        help_label.setObjectName("mutedLabel")
        input_layout.addWidget(help_label)

        layout.addWidget(input_box)
        layout.addStretch(1)
        return panel

    def _build_display_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("displayPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        status_card = QFrame()
        status_card.setObjectName("cardFrame")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(14, 14, 14, 14)
        status_layout.setSpacing(12)
        status_layout.addWidget(self._section_title("Current Ephemeris"))

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self.indicator_dot = QLabel()
        self.indicator_dot.setFixedSize(16, 16)
        self.indicator_dot.setObjectName("indicatorDot")

        self.visibility_summary = QLabel("Below horizon")
        self.visibility_summary.setObjectName("statusValueLabel")

        self.status_detail = QLabel("Waiting for data")
        self.status_detail.setWordWrap(True)
        self.status_detail.setObjectName("mutedLabel")

        status_summary_layout = QVBoxLayout()
        status_summary_layout.setSpacing(3)
        status_summary_layout.addWidget(self.visibility_summary)
        status_summary_layout.addWidget(self.status_detail)

        top_row.addWidget(self.indicator_dot, 0, Qt.AlignmentFlag.AlignTop)
        top_row.addLayout(status_summary_layout)
        top_row.addStretch(1)

        status_layout.addLayout(top_row)

        metrics_grid = QGridLayout()
        metrics_grid.setHorizontalSpacing(12)
        metrics_grid.setVerticalSpacing(12)

        self.value_labels = {}
        fields = [
            ("UTC Time", "utc_time"),
            ("Local Time", "local_time"),
            ("RA", "ra_deg"),
            ("Dec", "dec_deg"),
            ("Azimuth", "az_deg"),
            ("Elevation", "el_deg"),
            ("Solar Elongation", "solar_elong_deg"),
            ("Compass", "compass_direction"),
            ("Visibility", "visibility_status"),
        ]

        for index, (label_text, key) in enumerate(fields):
            row = index // 3
            col = index % 3
            card, value_label = self._make_metric_card(label_text)
            self.value_labels[key] = value_label
            metrics_grid.addWidget(card, row, col)

        status_layout.addLayout(metrics_grid)
        layout.addWidget(status_card)

        chart_log_splitter = QSplitter(Qt.Orientation.Vertical)
        chart_log_splitter.setObjectName("chartLogSplitter")
        chartLogHandleWidth = 10
        chart_log_splitter.setChildrenCollapsible(False)
        chart_log_splitter.setHandleWidth(chartLogHandleWidth)

        plot_card = QFrame()
        plot_card.setObjectName("cardFrame")
        plot_layout = QVBoxLayout(plot_card)
        plot_layout.setContentsMargins(18, 18, 18, 18)
        plot_layout.setSpacing(12)
        plot_layout.addWidget(self._section_title("Sky Projection (Alt-Az)"))
        self.sky_plot = pg.PlotWidget()
        self.sky_plot.setBackground("#07111f")
        self.sky_plot.hideAxis("left")
        self.sky_plot.hideAxis("bottom")
        self.sky_plot.setAspectLocked(True)
        self.sky_plot.setMouseEnabled(x=False, y=False)
        self.sky_plot.setXRange(-1.1, 1.1, padding=0)
        self.sky_plot.setYRange(-1.1, 1.1, padding=0)
        self.sky_plot.setMinimumHeight(250)
        self.sky_plot.setMaximumHeight(250)
        self.sky_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._init_sky_projection_plot()
        plot_layout.addWidget(self.sky_plot)

        plot_layout.addWidget(self._section_title("Live Plot"))
        self.elevation_plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self.elevation_plot.setBackground("#07111f")
        self.elevation_plot.showGrid(x=True, y=True, alpha=0.18)
        self.elevation_plot.addLegend(offset=(12, 8))
        self.elevation_plot.setLabel("left", "Elevation (deg)")
        self.elevation_plot.setLabel("bottom", "UTC time")
        self.elevation_plot.setYRange(-90.0, 90.0)
        self.elevation_plot.setMouseEnabled(x=True, y=False)
        self.elevation_plot.getPlotItem().enableAutoRange(x=True, y=False)
        self.elevation_plot.setLimits(yMin=-90.0, yMax=90.0, minYRange=180.0, maxYRange=180.0)
        self.elevation_plot.setMinimumHeight(185)
        self.elevation_plot.setMaximumHeight(185)
        self.elevation_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.el_curve = self.elevation_plot.plot(pen=pg.mkPen("#fbbf24", width=2.2), name="Elevation")
        self.el_prediction_curve = self.elevation_plot.plot(
            pen=pg.mkPen("#34d399", width=2, style=Qt.PenStyle.DashLine),
            name="Elevation Forecast",
        )
        self.elevation_cursor = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen("#22c55e", width=1.1, style=Qt.PenStyle.DashLine),
        )
        self.elevation_cursor.setVisible(False)
        self.elevation_plot.addItem(self.elevation_cursor)

        self.azimuth_plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self.azimuth_plot.setBackground("#07111f")
        self.azimuth_plot.showGrid(x=True, y=True, alpha=0.18)
        self.azimuth_plot.addLegend(offset=(12, 8))
        self.azimuth_plot.setLabel("left", "Azimuth (deg)")
        self.azimuth_plot.setLabel("bottom", "UTC time")
        self.azimuth_plot.setYRange(0.0, 360.0)
        self.azimuth_plot.setMouseEnabled(x=True, y=False)
        self.azimuth_plot.getPlotItem().enableAutoRange(x=True, y=False)
        self.azimuth_plot.setLimits(yMin=0.0, yMax=360.0, minYRange=360.0, maxYRange=360.0)
        self.azimuth_plot.setMinimumHeight(185)
        self.azimuth_plot.setMaximumHeight(185)
        self.azimuth_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.az_curve = self.azimuth_plot.plot(pen=pg.mkPen("#7dd3fc", width=2.2), name="Azimuth")
        self.az_prediction_curve = self.azimuth_plot.plot(
            pen=pg.mkPen("#34d399", width=2, style=Qt.PenStyle.DashLine),
            name="Azimuth Forecast",
        )
        self.azimuth_cursor = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen("#22c55e", width=1.1, style=Qt.PenStyle.DashLine),
        )
        self.azimuth_cursor.setVisible(False)
        self.azimuth_plot.addItem(self.azimuth_cursor)

        self.azimuth_plot.setXLink(self.elevation_plot)
        self._set_initial_plot_time_window()

        plot_layout.addWidget(self.elevation_plot)
        plot_layout.addWidget(self.azimuth_plot)

        log_card = QFrame()
        log_card.setObjectName("cardFrame")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(14, 14, 14, 14)
        log_layout.setSpacing(12)
        log_layout.addWidget(self._section_title("Sample Log"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("logView")
        self.log_view.setMaximumBlockCount(0)
        self.log_view.setMinimumHeight(180)
        log_layout.addWidget(self.log_view)

        chart_log_splitter.addWidget(plot_card)
        chart_log_splitter.addWidget(log_card)
        chart_log_splitter.setStretchFactor(0, 2)
        chart_log_splitter.setStretchFactor(1, 1)

        layout.addWidget(chart_log_splitter, 1)
        return panel

    def _init_sky_projection_plot(self) -> None:
        ring_angles = [math.radians(deg) for deg in range(361)]
        base_pen = pg.mkPen("#334155", width=1)
        horizon_pen = pg.mkPen("#94a3b8", width=1.4)

        for radius, pen in ((1.0, horizon_pen), (2.0 / 3.0, base_pen), (1.0 / 3.0, base_pen)):
            xs = [radius * math.cos(angle) for angle in ring_angles]
            ys = [radius * math.sin(angle) for angle in ring_angles]
            self.sky_plot.plot(xs, ys, pen=pen)

        self.sky_plot.plot([-1.0, 1.0], [0.0, 0.0], pen=base_pen)
        self.sky_plot.plot([0.0, 0.0], [-1.0, 1.0], pen=base_pen)

        for text, pos in (
            ("N", (0.0, 1.06)),
            ("E", (1.08, 0.0)),
            ("S", (0.0, -1.09)),
            ("W", (-1.08, 0.0)),
            ("60\N{DEGREE SIGN}", (0.05, 0.35)),
            ("30\N{DEGREE SIGN}", (0.05, 0.68)),
            ("Horizon", (0.12, 0.9)),
        ):
            item = pg.TextItem(text, color="#94a3b8", anchor=(0.5, 0.5))
            item.setPos(*pos)
            self.sky_plot.addItem(item)

        self.sky_track_curve = self.sky_plot.plot(pen=pg.mkPen("#38bdf8", width=1.5))
        self.sky_prediction_curve = self.sky_plot.plot(pen=pg.mkPen("#22c55e", width=2, style=Qt.PenStyle.DashLine))
        self.sky_target_marker = pg.ScatterPlotItem(size=13, brush=pg.mkBrush("#f59e0b"), pen=pg.mkPen("#fbbf24", width=2))
        self.sky_plot.addItem(self.sky_target_marker)
        self.sky_target_text = pg.TextItem("", color="#fbbf24", anchor=(0.5, 1.3))
        self.sky_plot.addItem(self.sky_target_text)

    def _sky_xy_from_altaz(self, az_deg: float, el_deg: float) -> tuple[float, float]:
        clamped_el = max(-90.0, min(90.0, el_deg))
        radius = (90.0 - clamped_el) / 90.0
        radius = max(0.0, min(1.0, radius))
        az_rad = math.radians(az_deg)
        x = radius * math.sin(az_rad)
        y = radius * math.cos(az_rad)
        return x, y

    def _update_sky_projection(self, sample: EphemerisSample) -> None:
        trail_points = list(zip(self.azimuths, self.elevations))[-60:]
        xs: list[float] = []
        ys: list[float] = []
        for az_deg, el_deg in trail_points:
            x, y = self._sky_xy_from_altaz(az_deg, el_deg)
            xs.append(x)
            ys.append(y)
        self.sky_track_curve.setData(xs, ys)

        predicted_xy = [self._sky_xy_from_altaz(row.az_deg, row.el_deg) for row in self.predicted_samples]
        pred_xs = [point[0] for point in predicted_xy]
        pred_ys = [point[1] for point in predicted_xy]
        self.sky_prediction_curve.setData(pred_xs, pred_ys)

        display_sample = sample
        marker_label_prefix = "LIVE"
        marker_color = "#22c55e" if sample.el_deg > 0 else "#ef4444"
        if not self.follow_live_projection and self.predicted_samples:
            offset_minutes = int(self.timeline_slider.value())
            prediction_index = min(len(self.predicted_samples) - 1, offset_minutes // self.prediction_step_minutes)
            display_sample = self.predicted_samples[prediction_index]
            marker_label_prefix = f"T+{offset_minutes}m"
            marker_color = "#38bdf8"

        marker_x, marker_y = self._sky_xy_from_altaz(display_sample.az_deg, display_sample.el_deg)
        self.sky_target_marker.setData([marker_x], [marker_y], brush=pg.mkBrush(marker_color))
        self.sky_target_text.setText(
            f"{marker_label_prefix} | Az {display_sample.az_deg:.1f}\N{DEGREE SIGN} | El {display_sample.el_deg:.1f}\N{DEGREE SIGN}"
        )
        self.sky_target_text.setPos(marker_x, marker_y)

    def _should_refresh_prediction(self, sample: EphemerisSample) -> bool:
        if self.last_prediction_anchor_utc is None:
            return True
        elapsed = (sample.utc_time - self.last_prediction_anchor_utc).total_seconds()
        return elapsed >= self.prediction_refresh_seconds

    def _request_prediction_trajectory(self, anchor_time: datetime) -> None:
        if self.prediction_request_thread and self.prediction_request_thread.isRunning():
            return

        start_time = anchor_time.astimezone(timezone.utc)
        stop_time = start_time + timedelta(minutes=self.prediction_horizon_minutes)
        target_command = self.state.target_command
        location = self.state.location

        def action() -> list[EphemerisSample]:
            return self.fetcher.fetch_ephemeris_range(
                target_command=target_command,
                location=location,
                start_time=start_time,
                stop_time=stop_time,
                step_minutes=self.prediction_step_minutes,
            )

        thread = RequestThread(action, self)
        self.prediction_request_thread = thread
        thread.result_ready.connect(self._handle_prediction_result)
        thread.error_occurred.connect(self._handle_prediction_error)
        thread.start()

    @Slot(object)
    def _handle_prediction_result(self, payload: object) -> None:
        if not isinstance(payload, list):
            self._append_log("[WARN] Unexpected prediction payload.")
            return

        rows = [row for row in payload if isinstance(row, EphemerisSample)]
        if not rows:
            self._append_log("[WARN] Prediction returned no samples.")
            return

        self.predicted_samples = rows
        self.last_prediction_anchor_utc = rows[0].utc_time
        self._update_prediction_plot_curves()
        self.timeline_slider.setRange(0, max(0, (len(rows) - 1) * self.prediction_step_minutes))
        self.back_to_live_button.setEnabled(not self.follow_live_projection)
        if self.state.latest_sample:
            self._update_sky_projection(self.state.latest_sample)
        self._append_log(
            f"Prediction refreshed: {len(rows)} samples for the next {self.prediction_horizon_minutes // 60}h."
        )

    @Slot(str)
    def _handle_prediction_error(self, message: str) -> None:
        self._append_log(f"[WARN] Prediction update failed: {message}")

    def _section_title(self, text: str, *, compact: bool = False) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitleCompact" if compact else "sectionTitle")
        return label

    def _make_metric_card(self, label_text: str) -> tuple[QFrame, QLabel]:
        card = QFrame()
        card.setObjectName("metricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)

        label = QLabel(label_text)
        label.setObjectName("metricLabel")

        value = QLabel("-")
        value.setObjectName("metricValue")
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addWidget(label)
        layout.addWidget(value)
        layout.addStretch(1)
        return card, value

    def _make_spinbox(self, minimum: float, maximum: float, decimals: int, value: float) -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox()
        spinbox.setRange(minimum, maximum)
        spinbox.setDecimals(decimals)
        spinbox.setValue(value)
        spinbox.setKeyboardTracking(False)
        spinbox.setAlignment(Qt.AlignmentFlag.AlignRight)
        return spinbox

    def _apply_dark_theme(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #020817;
                color: #e2e8f0;
                font-size: 12px;
            }

            QMainWindow, #rootWidget {
                background: #020817;
            }

            #heroFrame {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #0f172a,
                    stop: 0.55 #0b1b34,
                    stop: 1 #111827
                );
                border: 1px solid #1f3658;
                border-radius: 16px;
            }

            #controlsPanel, #displayPanel {
                background: transparent;
                border: none;
            }

            #cardFrame {
                background: #081120;
                border: 1px solid #17304d;
                border-radius: 15px;
            }

            #subCardFrame {
                background: #0b1627;
                border: 1px solid #1f3658;
                border-radius: 12px;
            }

            #metricCard {
                background: #0c182b;
                border: 1px solid #17304d;
                border-radius: 12px;
            }

            #titleLabel {
                color: #f8fafc;
                background: transparent;
            }

            #headerBadge {
                background: rgba(15, 23, 42, 0.72);
                color: #93c5fd;
                border: 1px solid #27507a;
                border-radius: 12px;
                padding: 6px 10px;
                font-size: 12px;
                font-weight: 700;
                min-width: 112px;
            }

            #subtitleLabel, #mutedLabel {
                color: #94a3b8;
                background: transparent;
            }

            #controlsPanel {
                min-width: 280px;
            }

            #controlsScrollArea, #displayScrollArea {
                background: transparent;
                border: none;
            }

            #controlsScrollArea > QWidget > QWidget,
            #displayScrollArea > QWidget > QWidget {
                background: transparent;
            }

            #sectionTitle {
                color: #f8fafc;
                font-size: 14px;
                font-weight: 700;
                padding-bottom: 2px;
                background: transparent;
            }

            #sectionTitleCompact {
                color: #dbeafe;
                font-size: 13px;
                font-weight: 700;
                background: transparent;
            }

            #cardPrimaryLabel {
                color: #f8fafc;
                font-size: 14px;
                font-weight: 700;
                background: transparent;
            }

            #metricLabel {
                color: #8ba4c7;
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 0.3px;
                background: transparent;
            }

            #metricValue {
                color: #f8fafc;
                font-size: 14px;
                font-weight: 700;
                background: transparent;
            }

            #statusValueLabel {
                color: #f8fafc;
                font-size: 19px;
                font-weight: 800;
                background: transparent;
            }

            #timelineBadge {
                background: rgba(59, 130, 246, 0.16);
                color: #93c5fd;
                border: 1px solid #27507a;
                border-radius: 8px;
                padding: 3px 8px;
                font-weight: 700;
                min-width: 50px;
            }

            #indicatorDot {
                border-radius: 8px;
                background: #dc2626;
                border: 1px solid #1f2937;
            }

            QDoubleSpinBox {
                background: #0f172a;
                color: #f8fafc;
                border: 1px solid #274060;
                border-radius: 10px;
                padding: 7px 10px;
                min-height: 24px;
                selection-background-color: #2563eb;
            }

            QDoubleSpinBox:focus {
                border: 1px solid #38bdf8;
            }

            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                background: transparent;
                width: 18px;
                border: none;
            }

            QPushButton {
                background: #18283b;
                color: #e5eefb;
                border: 1px solid #28415d;
                border-radius: 10px;
                padding: 8px 12px;
                font-weight: 700;
            }

            QPushButton:hover {
                background: #203349;
            }

            QPushButton:pressed {
                background: #132033;
            }

            QPushButton:disabled {
                color: #64748b;
                background: #0f172a;
                border-color: #1f2937;
            }

            #primaryButton {
                background: #2563eb;
                border-color: #3b82f6;
                color: #eff6ff;
            }

            #primaryButton:hover {
                background: #2d6ef3;
            }

            #secondaryButton {
                background: #13253a;
                border-color: #28415d;
            }

            #dangerButton {
                background: #2b1620;
                border-color: #5d2233;
                color: #fecdd3;
            }

            #dangerButton:hover {
                background: #341823;
            }

            #ghostButton {
                background: transparent;
                border: 1px solid #28415d;
                color: #cbd5e1;
            }

            QSlider::groove:horizontal {
                border: none;
                height: 6px;
                border-radius: 3px;
                background: #132033;
            }

            QSlider::sub-page:horizontal {
                background: #2563eb;
                border-radius: 3px;
            }

            QSlider::handle:horizontal {
                background: #e2e8f0;
                width: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }

            QPlainTextEdit {
                background: #07111f;
                color: #dbeafe;
                border: 1px solid #17304d;
                border-radius: 12px;
                padding: 10px;
                font-family: SF Mono, Menlo, Consolas, monospace;
                font-size: 12px;
            }

            QScrollBar:vertical {
                background: transparent;
                width: 10px;
                margin: 2px;
            }

            QScrollBar::handle:vertical {
                background: #274060;
                border-radius: 5px;
                min-height: 24px;
            }

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }

            QSplitter::handle {
                background: transparent;
            }

            QStatusBar {
                background: #020817;
                color: #8ba4c7;
            }

            QToolTip {
                background: #111827;
                color: #e5eefb;
                border: 1px solid #334155;
            }
            """
        )

    def _bind_signals(self) -> None:
        self.start_button.clicked.connect(self.start_tracking)
        self.stop_button.clicked.connect(self.stop_tracking)
        self.load_ip_button.clicked.connect(self.load_ip_location)
        self.timeline_slider.valueChanged.connect(self._on_timeline_slider_changed)
        self.back_to_live_button.clicked.connect(self._set_projection_live)

    def _sync_controls_from_state(self) -> None:
        self.latitude_spin.setValue(self.state.location.latitude_deg)
        self.longitude_spin.setValue(self.state.location.longitude_deg)
        self.elevation_spin.setValue(self.state.location.elevation_km)
        self.interval_spin.setValue(float(self.state.refresh_interval_sec))

    def _current_location_from_controls(self) -> ObserverLocation:
        return ObserverLocation(
            latitude_deg=float(self.latitude_spin.value()),
            longitude_deg=float(self.longitude_spin.value()),
            elevation_km=float(self.elevation_spin.value()),
        )

    def _current_interval_from_controls(self) -> int:
        return max(1, int(self.interval_spin.value()))

    @Slot(int)
    def _on_timeline_slider_changed(self, offset_minutes: int) -> None:
        self.follow_live_projection = offset_minutes == 0
        if self.follow_live_projection:
            self.timeline_status_label.setText("LIVE")
        else:
            self.timeline_status_label.setText(f"Preview T+{offset_minutes} min")

        self.back_to_live_button.setEnabled(not self.follow_live_projection)
        self._update_timeline_selection(offset_minutes)

    @Slot()
    def _set_projection_live(self) -> None:
        self.timeline_slider.setValue(0)
        self.follow_live_projection = True
        self.timeline_status_label.setText("LIVE")
        self.back_to_live_button.setEnabled(False)
        self._update_timeline_selection(0)

    def _render_sample_fields(self, sample: EphemerisSample) -> None:
        self.value_labels["utc_time"].setText(sample.utc_time.strftime("%Y-%m-%d %H:%M:%S UTC"))
        self.value_labels["local_time"].setText(format_local_time(sample.utc_time))
        self.value_labels["ra_deg"].setText(f"{sample.ra_deg:.6f} deg")
        self.value_labels["dec_deg"].setText(f"{sample.dec_deg:.6f} deg")
        self.value_labels["az_deg"].setText(f"{sample.az_deg:.3f} deg")
        self.value_labels["el_deg"].setText(f"{sample.el_deg:.3f} deg")
        self.value_labels["solar_elong_deg"].setText(f"{sample.solar_elong_deg:.3f} deg")
        self.value_labels["compass_direction"].setText(sample.compass_direction)
        self.value_labels["visibility_status"].setText(sample.visibility_status)
        self._set_indicator(sample.el_deg, sample.visibility_status)

    def _set_plot_cursor(self, sample: EphemerisSample, *, preview: bool) -> None:
        timestamp = sample.utc_time.timestamp()
        color = "#38bdf8" if preview else "#22c55e"
        pen = pg.mkPen(color, width=1.2, style=Qt.PenStyle.DashLine)
        self.elevation_cursor.setPen(pen)
        self.azimuth_cursor.setPen(pen)
        self.elevation_cursor.setPos(timestamp)
        self.azimuth_cursor.setPos(timestamp)
        self.elevation_cursor.setVisible(True)
        self.azimuth_cursor.setVisible(True)

    def _set_initial_plot_time_window(self) -> None:
        now_ts = datetime.now(timezone.utc).timestamp()
        half_window_sec = 30 * 60
        self.elevation_plot.setXRange(now_ts - half_window_sec, now_ts + half_window_sec, padding=0)

    def _update_prediction_plot_curves(self) -> None:
        if not self.predicted_samples:
            self.el_prediction_curve.setData([], [])
            self.az_prediction_curve.setData([], [])
            return

        pred_timestamps = [row.utc_time.timestamp() for row in self.predicted_samples]
        pred_elevations = [row.el_deg for row in self.predicted_samples]
        pred_azimuths = [row.az_deg for row in self.predicted_samples]
        self.el_prediction_curve.setData(pred_timestamps, pred_elevations)
        self.az_prediction_curve.setData(pred_timestamps, pred_azimuths)

    def _update_timeline_selection(self, offset_minutes: int) -> None:
        if self.state.latest_sample is None:
            return

        self._update_sky_projection(self.state.latest_sample)

        if offset_minutes == 0 or not self.predicted_samples:
            self._render_sample_fields(self.state.latest_sample)
            self._set_plot_cursor(self.state.latest_sample, preview=False)
            return

        prediction_index = min(len(self.predicted_samples) - 1, offset_minutes // self.prediction_step_minutes)
        preview_sample = self.predicted_samples[prediction_index]
        self._render_sample_fields(preview_sample)
        self._set_plot_cursor(preview_sample, preview=True)

    def _set_tracking_ui(self, running: bool) -> None:
        self.state.is_tracking = running
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.latitude_spin.setEnabled(not running)
        self.longitude_spin.setEnabled(not running)
        self.elevation_spin.setEnabled(not running)
        self.interval_spin.setEnabled(not running)

    def _update_status_banner(self, message: str) -> None:
        self.status_detail.setText(message)
        self.statusBar().showMessage(message)

    def _append_log(self, line: str) -> None:
        self.log_lines.append(line)
        self.log_view.setPlainText("\n".join(self.log_lines))
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_view.setTextCursor(cursor)
        self.log_view.ensureCursorVisible()

    def _set_indicator(self, elevation_deg: float, visibility_text: str) -> None:
        color = "#22c55e" if elevation_deg > 0 else "#ef4444"
        self.indicator_dot.setStyleSheet(
            f"background: {color}; border-radius: 9px; border: 1px solid #1f2937;"
        )
        self.visibility_summary.setText(visibility_text)

    def _update_sample_display(self, sample: EphemerisSample) -> None:
        self.state.latest_sample = sample
        self.state.history.append(sample)
        if len(self.state.history) > 1000:
            self.state.history.pop(0)

        if self.follow_live_projection:
            self._render_sample_fields(sample)
            self._set_plot_cursor(sample, preview=False)
        self._update_plot(sample)
        self._update_sky_projection(sample)
        if self._should_refresh_prediction(sample):
            self._request_prediction_trajectory(sample.utc_time)

        log_line = (
            f"{sample.utc_time.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
            f"Local {format_local_time(sample.utc_time)} | "
            f"RA {sample.ra_deg:.6f} deg | Dec {sample.dec_deg:.6f} deg | "
            f"Az {sample.az_deg:.3f} deg ({sample.compass_direction}) | "
            f"El {sample.el_deg:.3f} deg | S-O-T {sample.solar_elong_deg:.3f} deg | "
            f"{sample.visibility_status}"
        )
        self._append_log(log_line)
        self._update_status_banner(f"Latest sample updated at {sample.utc_time.strftime('%H:%M:%S UTC')}.")

    def _update_plot(self, sample: EphemerisSample) -> None:
        timestamp = sample.utc_time.timestamp()
        self.timestamps.append(timestamp)
        self.azimuths.append(sample.az_deg)
        self.elevations.append(sample.el_deg)
        self.az_curve.setData(list(self.timestamps), list(self.azimuths))
        self.el_curve.setData(list(self.timestamps), list(self.elevations))

    def _set_error_state(self, message: str) -> None:
        self.state.last_error = message
        self._append_log(f"[ERROR] {message}")
        self._update_status_banner(f"Error: {message}")

    @Slot()
    def load_ip_location(self) -> None:
        if self.pending_request_thread and self.pending_request_thread.isRunning():
            return

        self._update_status_banner("Looking up location from current IP...")
        self.load_ip_button.setEnabled(False)

        def action() -> tuple[ObserverLocation, str]:
            return self.fetcher.fetch_ip_location()

        thread = RequestThread(action, self)
        self.pending_request_thread = thread
        thread.result_ready.connect(self._handle_ip_location)
        thread.error_occurred.connect(self._handle_request_error)
        thread.finished.connect(lambda: self.load_ip_button.setEnabled(True))
        thread.start()

    @Slot(object)
    def _handle_ip_location(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            self._set_error_state("Unexpected IP lookup result.")
            return

        location, label = payload
        if not isinstance(location, ObserverLocation):
            self._set_error_state("Unexpected IP lookup location payload.")
            return

        self.state.location = location
        self.latitude_spin.setValue(location.latitude_deg)
        self.longitude_spin.setValue(location.longitude_deg)
        self.elevation_spin.setValue(location.elevation_km)

        if label:
            self._append_log(f"IP location loaded: {label} ({location.latitude_deg:.6f}, {location.longitude_deg:.6f})")
            self._update_status_banner(f"IP location loaded for {label}.")
        else:
            self._append_log(
                f"IP location loaded: ({location.latitude_deg:.6f}, {location.longitude_deg:.6f})"
            )
            self._update_status_banner("IP location loaded.")

    @Slot(str)
    def _handle_request_error(self, message: str) -> None:
        self._set_error_state(message)

    @Slot()
    def start_tracking(self) -> None:
        if self.tracking_thread and self.tracking_thread.isRunning():
            self._update_status_banner("Tracking is already running.")
            return

        if not self.state.target_command.strip():
            self._set_error_state("Target command is not configured.")
            return

        location = self._current_location_from_controls()
        interval_sec = self._current_interval_from_controls()
        self.state.location = location
        self.state.refresh_interval_sec = interval_sec

        self.tracking_thread = TrackingThread(self.fetcher, self.state, self)
        self.tracking_thread.sample_ready.connect(self._update_sample_display)
        self.tracking_thread.error_occurred.connect(self._set_error_state)
        self.tracking_thread.status_message.connect(self._update_status_banner)
        self.tracking_thread.finished.connect(self._on_tracking_finished)

        self._set_tracking_ui(True)
        self.predicted_samples.clear()
        self.last_prediction_anchor_utc = None
        self.follow_live_projection = True
        self.timeline_status_label.setText("LIVE")
        self.timeline_slider.setValue(0)
        self.timeline_slider.setRange(0, self.prediction_horizon_minutes)
        self.back_to_live_button.setEnabled(False)
        self.sky_prediction_curve.setData([], [])
        self._update_prediction_plot_curves()
        self._append_log(
            f"Tracking started for lat={location.latitude_deg:.6f}, lon={location.longitude_deg:.6f}, elev={location.elevation_km:.3f} km, interval={interval_sec}s"
        )
        self.tracking_thread.start()

    @Slot()
    def stop_tracking(self) -> None:
        if self.tracking_thread and self.tracking_thread.isRunning():
            self._append_log("Stopping tracking...")
            self.tracking_thread.request_stop()
            self.tracking_thread.wait(5000)

    @Slot()
    def _on_tracking_finished(self) -> None:
        self._set_tracking_ui(False)
        self.back_to_live_button.setEnabled(False)
        self._append_log("Tracking stopped.")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.tracking_thread and self.tracking_thread.isRunning():
            self.tracking_thread.request_stop()
            self.tracking_thread.wait(5000)
        event.accept()


def run_app(state: TrackerState | None = None, config: TrackerAppConfig | None = None) -> int:
    import sys

    app_config = config or TrackerAppConfig()
    app = QApplication(sys.argv)
    app.setApplicationName(app_config.app_name)
    app.setOrganizationName(app_config.organization_name)

    icon_path = Path(__file__).resolve().parent / "static" / "solar_system.jpg"
    rounded_icon = _build_rounded_icon(icon_path)
    if rounded_icon is not None and not rounded_icon.isNull():
        app.setWindowIcon(rounded_icon)

    window = AstronomyTrackerWindow(state=state, config=app_config)
    if rounded_icon is not None and not rounded_icon.isNull():
        window.setWindowIcon(rounded_icon)
    window.show()
    return app.exec()


def _build_rounded_icon(icon_path: Path, size: int = 256, corner_ratio: float = 0.22) -> QIcon | None:
    if not icon_path.exists():
        return None

    source = QPixmap(str(icon_path))
    if source.isNull():
        return None

    # Fill the icon square while preserving aspect ratio.
    scaled = source.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )

    rounded = QPixmap(size, size)
    rounded.fill(Qt.GlobalColor.transparent)

    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    radius = size * corner_ratio
    path.addRoundedRect(0, 0, size, size, radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()

    return QIcon(rounded)
