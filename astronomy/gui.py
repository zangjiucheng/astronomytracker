"""
gui.py

This module provides the main window and entry point for the
restructured astronomy tracker GUI.  It consolidates the logic from
the original monolithic ``gui.py`` while importing the tab widgets
defined in :mod:`astronomy.components.controls_tab`,
:mod:`astronomy.components.status_tab` and
:mod:`astronomy.components.plots_tab`.  The public API remains
largely the same: the ``AstronomyTrackerWindow`` class encapsulates
the interface and ``run_app`` launches the Qt application.  Users
should replace the original ``gui.py`` with this file and include
the accompanying modules in the same package.

In addition to the tabbed interface, this implementation includes the
sky projection drawing routines, prediction scheduling and weather
update logic that were part of the original monolithic GUI.  These
methods remain on the window class so that the plots tab can call
``_init_sky_projection_plot`` and ``_update_sky_projection`` when
needed.  Separating the GUI into multiple files improves clarity and
maintainability without sacrificing functionality.
"""

from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pyqtgraph as pg
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPixmap,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from astronomy.api_fetcher import HorizonsFetcher
from astronomy.observation_scorer import ObservationContext, ObservationScoreResult
from astronomy.scorer_factory import create_scorer
from astronomy.tracker_state import (
    EphemerisSample,
    ObserverLocation,
    TrackerState,
    format_local_time,
)

# Import tab widgets from our components package.
from .components.controls_tab import ControlsTab
from .components.status_tab import StatusTab
from .components.plots_tab import PlotsTab

# Enable anti‑aliasing globally for pyqtgraph plots.
pg.setConfigOptions(antialias=True)


@dataclass(frozen=True)
class TrackerAppConfig:
    app_name: str = "Astronomy Tracker"
    organization_name: str = "Astronomy"
    window_title: str = "Astronomy Tracker"
    header_title: str = "Real-Time Astronomy Tracker"
    header_subtitle: str = "PySide6 desktop tracker with live JPL Horizons sampling, historical log, and azimuth/elevation plot."
    target_name: str = "Target"
    scorer_target_type: str = "default"


class RequestThread(QThread):
    """Generic thread wrapper for performing actions off the GUI thread."""

    result_ready = Signal(object)
    error_occurred = Signal(str)

    def __init__(
        self, action: Callable[[], object], parent: QObject | None = None
    ) -> None:
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
    """Background thread that periodically fetches current ephemeris samples."""

    sample_ready = Signal(object)
    error_occurred = Signal(str)
    status_message = Signal(str)

    def __init__(
        self,
        fetcher: HorizonsFetcher,
        state: TrackerState,
        parent: QObject | None = None,
    ) -> None:
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
                sample = self._fetcher.fetch_current_ephemeris(
                    state.target_command, state.location
                )
                self.sample_ready.emit(sample)
            except Exception as exc:  # noqa: BLE001
                self.error_occurred.emit(str(exc))
            interval = max(1, int(state.refresh_interval_sec))
            if self._stop_event.wait(interval):
                break
        self.status_message.emit("Tracking stopped")


class AstronomyTrackerWindow(QMainWindow):
    """Main application window for the astronomy tracker.

    This window orchestrates the various UI tabs, handles incoming
    ephemeris samples, manages prediction and weather refresh logic and
    renders plots.  It largely mirrors the functionality of the
    original monolithic ``gui.py`` but delegates UI construction to
    separate component modules.
    """

    def __init__(
        self, state: TrackerState | None = None, config: TrackerAppConfig | None = None
    ) -> None:
        super().__init__()
        self.fetcher = HorizonsFetcher()
        self.state = state or TrackerState()
        self.config = config or TrackerAppConfig()
        # Limits on history and plot buffers.
        self.history_limit = 400
        self.plot_limit = 180
        self.log_lines: deque[str] = deque(maxlen=self.history_limit)
        self.timestamps: deque[float] = deque(maxlen=self.plot_limit)
        self.azimuths: deque[float] = deque(maxlen=self.plot_limit)
        self.elevations: deque[float] = deque(maxlen=self.plot_limit)
        self.observation_scores: deque[float] = deque(maxlen=self.plot_limit)
        self.weather_scores: deque[float] = deque(maxlen=self.plot_limit)
        # Prediction settings.
        self.prediction_horizon_minutes = 24 * 60
        self.prediction_step_minutes = 1
        self.prediction_refresh_seconds = 300
        self.follow_live_projection = True
        self.predicted_samples: list[EphemerisSample] = []
        self.predicted_observation_scores: list[float] = []
        self.predicted_weather_scores: list[float] = []
        self.last_prediction_anchor_utc: datetime | None = None
        # Weather update settings.
        self.weather_refresh_seconds = 2 * 60
        self.last_weather_update_utc: datetime | None = None
        self.latest_weather: dict[str, float | None] | None = None
        self.hourly_forecast: dict[datetime, dict[str, float | None]] = {}
        # Threads for background work.
        self.tracking_thread: TrackingThread | None = None
        self.pending_request_thread: RequestThread | None = None
        self.prediction_request_thread: RequestThread | None = None
        self.weather_request_thread: RequestThread | None = None
        # Active scorer instance used to evaluate observation quality.
        self.active_scorer = create_scorer(self.config.scorer_target_type)
        # Configure the window itself.
        self.setWindowTitle(self.config.window_title)
        self.resize(1320, 860)
        # Build the UI, apply theme and bind signals.
        self._build_ui()
        self._apply_dark_theme()
        self._bind_signals()
        self._sync_controls_from_state()
        self._update_status_banner(
            "Ready. Enter coordinates or use IP location, then start tracking."
        )

    # -----------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("rootWidget")
        central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setCentralWidget(central)

        self._bg_pixmap = QPixmap(
            str(
                Path(__file__).resolve().parent / "static" / "star-space-background.jpg"
            )
        )
        if not self._bg_pixmap.isNull():
            self._bg_label = QLabel(central)
            self._bg_label.lower()
            self._bg_label.setAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground, False
            )
            self._bg_label.setScaledContents(True)
            self._bg_label.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            QTimer.singleShot(0, self._rescale_bg)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(12)
        # Header at the top of the window with application title and subtitle.
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
        badge_column.addWidget(
            self.header_badge,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
        )
        badge_column.addStretch(1)
        header_layout.addLayout(title_stack, 1)
        header_layout.addLayout(badge_column)
        # Controls panel — always visible, not a tab.
        self.controls_panel = ControlsTab(self)
        # Instantiate the content tabs.  Each tab will attach widgets back onto this
        # window instance.
        self.status_tab = StatusTab(self)
        self.plots_tab = PlotsTab(self)
        if not hasattr(self, "sky_plot"):
            self._init_sky_projection_plot()
        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(10)
        content_row.addWidget(self.status_tab, 1)
        content_row.addWidget(self.plots_tab, 2)
        main_layout.addWidget(header)
        main_layout.addWidget(self.controls_panel)
        main_layout.addLayout(content_row, 1)
        # Status bar initial state.
        self.statusBar().showMessage("Ready")

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

    def _make_spinbox(
        self, minimum: float, maximum: float, decimals: int, value: float
    ) -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox()
        spinbox.setRange(minimum, maximum)
        spinbox.setDecimals(decimals)
        spinbox.setValue(value)
        spinbox.setKeyboardTracking(False)
        spinbox.setAlignment(Qt.AlignmentFlag.AlignRight)
        return spinbox

    def _apply_dark_theme(self) -> None:
        """Apply a dark colour palette to the entire window."""
        # Same stylesheet used by the original GUI.  Tabs inherit these rules.
        self.setStyleSheet(
            """
            QWidget {
                background: rgba(2, 8, 23, 0.6);
                color: #e2e8f0;
                font-size: 12px;
            }
            QMainWindow, #rootWidget {
            }
            #heroFrame {
                background: rgba(8, 17, 32, 0.75);
                border: 1px solid #1f3658;
                border-radius: 16px;
            }
            #controlsPanel, #displayPanel {
                background: transparent;
                border: none;
            }
            #cardFrame {
                background: rgba(8, 17, 32, 0.75);
                border: 1px solid #17304d;
                border-radius: 15px;
            }
            #subCardFrame {
                background: rgba(11, 22, 39, 0.75);
                border: 1px solid #1f3658;
                border-radius: 12px;
            }
            #metricCard {
                background: rgba(12, 24, 43, 0.75);
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
                padding: 3px 0;
                font-weight: 700;
                min-width: 120px;
                max-width: 120px;
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
        """Connect UI signals to handler methods."""
        self.start_button.clicked.connect(self.start_tracking)
        self.stop_button.clicked.connect(self.stop_tracking)
        self.load_ip_button.clicked.connect(self.load_ip_location)
        self.timeline_slider.valueChanged.connect(self._on_timeline_slider_changed)
        self.back_to_live_button.clicked.connect(self._set_projection_live)
        self.score_scatter.sigHovered.connect(self._on_score_hovered)
        self.score_prediction_scatter.sigHovered.connect(self._on_score_hovered)
        self.weather_scatter.sigHovered.connect(self._on_weather_hovered)
        self.weather_prediction_scatter.sigHovered.connect(self._on_weather_hovered)

    def _rescale_bg(self) -> None:
        if not hasattr(self, "_bg_pixmap") or self._bg_pixmap.isNull():
            return
        cw = self.centralWidget()
        if cw is None or not hasattr(self, "_bg_label"):
            return
        w, h = cw.size().width(), cw.size().height()
        self._bg_label.setFixedSize(w, h)
        self._bg_label.move(0, 0)
        self._bg_label.setPixmap(
            self._bg_pixmap.scaled(
                w,
                h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._rescale_bg()

    def _on_score_hovered(self, scatter, points, ev) -> None:
        if not len(points):
            return
        pt = points[0]
        x_ts = datetime.fromtimestamp(pt.pos().x()).strftime("%Y-%m-%d %H:%M:%S")
        y_val = pt.pos().y()
        label = f"Score: {y_val:.0f} at {x_ts}"
        if not hasattr(self, "_score_hover_text"):
            self._score_hover_text = pg.TextItem(
                "", color="#fbbf24", anchor=(0.5, 1.3), fill=pg.mkBrush("#0f172a")
            )
            self._score_hover_text.setFont(QFont("SF Mono", 9))
            self.score_plot.addItem(self._score_hover_text)
        self._score_hover_text.setText(label)
        self._score_hover_text.setPos(pt.pos().x(), pt.pos().y())
        self._score_hover_text.setVisible(True)

    def _on_weather_hovered(self, scatter, points, ev) -> None:
        if not len(points):
            return
        pt = points[0]
        x_ts = datetime.fromtimestamp(pt.pos().x()).strftime("%Y-%m-%d %H:%M:%S")
        y_val = pt.pos().y()
        label = f"Weather: {y_val:.0f}% at {x_ts}"
        if not hasattr(self, "_weather_hover_text"):
            self._weather_hover_text = pg.TextItem(
                "", color="#22d3ee", anchor=(0.5, 1.3), fill=pg.mkBrush("#0f172a")
            )
            self._weather_hover_text.setFont(QFont("SF Mono", 9))
            self.weather_plot.addItem(self._weather_hover_text)
        self._weather_hover_text.setText(label)
        self._weather_hover_text.setPos(pt.pos().x(), pt.pos().y())
        self._weather_hover_text.setVisible(True)

    def _sync_controls_from_state(self) -> None:
        """Set the control values based on the current tracker state."""
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

    # -----------------------------------------------------------------
    # Timeline and live projection handlers
    # -----------------------------------------------------------------
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

    # -----------------------------------------------------------------
    # Observation scoring helpers
    # -----------------------------------------------------------------
    def _estimate_sun_altitude(self, sample: EphemerisSample) -> float:
        token = sample.solar_presence.upper()
        if "*" in token:
            return 10.0
        if "C" in token:
            return -3.0
        if "N" in token:
            return -9.0
        if "A" in token:
            return -15.0
        return -25.0

    def _estimate_moon_context(
        self, sample: EphemerisSample
    ) -> tuple[float, float, float]:
        marker = sample.interferer_presence.lower()
        if "m" in marker:
            return 20.0, 0.7, 35.0
        return -90.0, 0.0, 180.0

    def _build_observation_context(self, sample: EphemerisSample) -> ObservationContext:
        moon_alt, moon_illumination, moon_separation = self._estimate_moon_context(
            sample
        )
        forecast_weather = self._weather_for_time(sample.utc_time)

        def weather_or_default(key: str, default: float) -> float:
            value = forecast_weather.get(key)
            if value is None:
                return default
            return float(value)

        return ObservationContext(
            target_alt=sample.el_deg,
            sun_alt=self._estimate_sun_altitude(sample),
            solar_elongation=sample.solar_elong_deg,
            moon_alt=moon_alt,
            moon_illumination=moon_illumination,
            moon_separation=moon_separation,
            cloud_cover=weather_or_default("cloud_cover", 0.0),
            humidity=weather_or_default("humidity", 55.0),
            visibility_km=weather_or_default("visibility_km", 15.0),
            wind_speed=weather_or_default("wind_speed", 8.0),
            temperature=weather_or_default("temperature", 10.0),
            dew_point=weather_or_default("dew_point", 2.0),
            seeing_arcsec=forecast_weather.get("seeing_arcsec"),
            transparency=forecast_weather.get("transparency"),
            bortle=None,
            azimuth=sample.az_deg,
            magnitude=None,
            target_name=self.config.target_name,
        )

    def _weather_for_time(self, t: datetime) -> dict[str, float | None]:
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if self.hourly_forecast:
            best_time: datetime | None = None
            best_data: dict[str, float | None] | None = None
            best_delta: float = 999999.0
            for ft, fw in self.hourly_forecast.items():
                delta = abs((ft - t).total_seconds())
                if delta < 3600 and delta < best_delta:
                    best_delta = delta
                    best_time = ft
                    best_data = fw
            if best_data is not None:
                return best_data
        current = self.latest_weather
        if current:
            return current
        return {}

    def _evaluate_observation(self, sample: EphemerisSample) -> ObservationScoreResult:
        return self.active_scorer.evaluate(self._build_observation_context(sample))

    def _score_color(self, score: float) -> QColor:
        score_01 = max(0.0, min(1.0, score / 100.0))
        anchors = [
            (0.0, QColor("#ef4444")),
            (0.5, QColor("#f59e0b")),
            (0.75, QColor("#84cc16")),
            (1.0, QColor("#14b8a6")),
        ]
        for idx in range(1, len(anchors)):
            left_pos, left_color = anchors[idx - 1]
            right_pos, right_color = anchors[idx]
            if score_01 <= right_pos:
                segment = (score_01 - left_pos) / max(1e-6, right_pos - left_pos)
                red = int(
                    round(
                        left_color.red()
                        + segment * (right_color.red() - left_color.red())
                    )
                )
                green = int(
                    round(
                        left_color.green()
                        + segment * (right_color.green() - left_color.green())
                    )
                )
                blue = int(
                    round(
                        left_color.blue()
                        + segment * (right_color.blue() - left_color.blue())
                    )
                )
                return QColor(red, green, blue)
        return anchors[-1][1]

    # -----------------------------------------------------------------
    # UI updates and plotting helpers
    # -----------------------------------------------------------------
    def _render_sample_fields(
        self,
        sample: EphemerisSample,
        score_result: ObservationScoreResult | None = None,
    ) -> None:
        ctx = self._build_observation_context(sample)
        if score_result is None:
            score_result = self.active_scorer.evaluate(ctx)
        self.value_labels["utc_time"].setText(
            sample.utc_time.strftime("%Y-%m-%d %H:%M:%S UTC")
        )
        self.value_labels["local_time"].setText(format_local_time(sample.utc_time))
        self.value_labels["ra_deg"].setText(f"{sample.ra_deg:.6f} deg")
        self.value_labels["dec_deg"].setText(f"{sample.dec_deg:.6f} deg")
        self.value_labels["az_deg"].setText(f"{sample.az_deg:.3f} deg")
        self.value_labels["el_deg"].setText(f"{sample.el_deg:.3f} deg")
        self.value_labels["solar_elong_deg"].setText(
            f"{sample.solar_elong_deg:.3f} deg"
        )
        self.value_labels["compass_direction"].setText(sample.compass_direction)
        self.value_labels["obs_score"].setText(f"{score_result.score}/100")
        self.value_labels["obs_grade"].setText(score_result.status)
        self.value_labels["obs_limiting"].setText(score_result.limiting_factor or "-")
        self.value_labels["weather_cloud"].setText(f"{ctx.cloud_cover:.0f}%")
        self.value_labels["weather_humidity"].setText(f"{ctx.humidity:.0f}%")
        self.value_labels["weather_wind"].setText(f"{ctx.wind_speed:.1f} km/h")
        self.value_labels["weather_visibility"].setText(f"{ctx.visibility_km:.1f} km")
        if score_result.reasons:
            reason_text = "; ".join(score_result.reasons[:3])
        else:
            reason_text = "No major limiting reason detected"
        self.reasons_summary.setText(f"Reasons: {reason_text}")
        self._set_indicator(score_result)

    def _set_plot_cursor(self, sample: EphemerisSample, *, preview: bool) -> None:
        timestamp = sample.utc_time.timestamp()
        color = "#38bdf8" if preview else "#22c55e"
        pen = pg.mkPen(color, width=1.2, style=Qt.PenStyle.DashLine)
        self.elevation_cursor.setPen(pen)
        self.azimuth_cursor.setPen(pen)
        self.score_cursor.setPen(pen)
        self.weather_cursor.setPen(pen)
        self.elevation_cursor.setPos(timestamp)
        self.azimuth_cursor.setPos(timestamp)
        self.score_cursor.setPos(timestamp)
        self.weather_cursor.setPos(timestamp)
        self.elevation_cursor.setVisible(True)
        self.azimuth_cursor.setVisible(True)
        self.score_cursor.setVisible(True)
        self.weather_cursor.setVisible(True)

    def _set_initial_plot_time_window(self) -> None:
        now_ts = datetime.now(timezone.utc).timestamp()
        half_window_sec = 30 * 60
        self.elevation_plot.setXRange(
            now_ts - half_window_sec, now_ts + half_window_sec
        )

    def _update_prediction_plot_curves(self) -> None:
        if not self.predicted_samples:
            self.el_prediction_curve.setData([], [])
            self.az_prediction_curve.setData([], [])
            self.score_prediction_curve.setData([], [])
            self.score_prediction_scatter.setData([], [])
            self.weather_prediction_curve.setData([], [])
            self.weather_prediction_scatter.setData([], [])
            self.predicted_observation_scores = []
            self.predicted_weather_scores = []
            return
        pred_timestamps = [row.utc_time.timestamp() for row in self.predicted_samples]
        pred_elevations = [row.el_deg for row in self.predicted_samples]
        pred_azimuths = [row.az_deg for row in self.predicted_samples]
        prediction_results = [
            self._evaluate_observation(row) for row in self.predicted_samples
        ]
        self.predicted_observation_scores = [
            float(result.score) for result in prediction_results
        ]
        self.predicted_weather_scores = [
            100.0 * float(result.subscores.get("weather", 0.0))
            for result in prediction_results
        ]
        self.el_prediction_curve.setData(pred_timestamps, pred_elevations)
        self.az_prediction_curve.setData(pred_timestamps, pred_azimuths)
        self.score_prediction_curve.setData(
            pred_timestamps, self.predicted_observation_scores
        )
        self.weather_prediction_curve.setData(
            pred_timestamps, self.predicted_weather_scores
        )
        forecast_brushes = [
            pg.mkBrush(self._score_color(score))
            for score in self.predicted_observation_scores
        ]
        self.score_prediction_scatter.setData(
            x=pred_timestamps,
            y=self.predicted_observation_scores,
            brush=forecast_brushes,
            pen=pg.mkPen("#0f172a", width=0.7),
            size=7,
        )
        weather_forecast_brushes = [
            pg.mkBrush(self._score_color(score))
            for score in self.predicted_weather_scores
        ]
        self.weather_prediction_scatter.setData(
            x=pred_timestamps,
            y=self.predicted_weather_scores,
            brush=weather_forecast_brushes,
            pen=pg.mkPen("#0f172a", width=0.7),
            size=7,
        )

    def _update_timeline_selection(self, offset_minutes: int) -> None:
        if self.state.latest_sample is None:
            return
        self._update_sky_projection(self.state.latest_sample)
        if offset_minutes == 0 or not self.predicted_samples:
            self._render_sample_fields(self.state.latest_sample)
            self._set_plot_cursor(self.state.latest_sample, preview=False)
            return
        prediction_index = min(
            len(self.predicted_samples) - 1,
            offset_minutes // self.prediction_step_minutes,
        )
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

    def _set_indicator(self, score_result: ObservationScoreResult) -> None:
        color = self._score_color(float(score_result.score))
        self.indicator_dot.setStyleSheet(
            f"background: {color.name()}; border-radius: 9px; border: 1px solid #1f2937;"
        )
        limiting = score_result.limiting_factor or "none"
        self.visibility_summary.setText(score_result.status)
        self.score_summary.setText(
            f"Score {score_result.score}/100 | Limiting: {limiting}"
        )

    def _update_sample_display(self, sample: EphemerisSample) -> None:
        self.state.latest_sample = sample
        self.state.history.append(sample)
        if len(self.state.history) > 1000:
            self.state.history.pop(0)
        score_result = self._evaluate_observation(sample)
        if self.follow_live_projection:
            self._render_sample_fields(sample, score_result)
            self._set_plot_cursor(sample, preview=False)
        self._update_plot(sample, score_result)
        self._update_sky_projection(sample)
        if self._should_refresh_prediction(sample):
            self._request_prediction_trajectory(sample.utc_time)
        if self._should_refresh_weather(sample):
            self._request_weather_update(sample.utc_time)
        log_line = (
            f"{sample.utc_time.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
            f"Local {format_local_time(sample.utc_time)} | "
            f"RA {sample.ra_deg:.6f} deg | Dec {sample.dec_deg:.6f} deg | "
            f"Az {sample.az_deg:.3f} deg ({sample.compass_direction}) | "
            f"El {sample.el_deg:.3f} deg | S-O-T {sample.solar_elong_deg:.3f} deg | "
            f"Score {score_result.score}/100 ({score_result.status})"
        )
        self._append_log(log_line)
        self._update_status_banner(
            f"Latest sample updated at {sample.utc_time.strftime('%H:%M:%S UTC')}."
        )

    def _update_plot(
        self, sample: EphemerisSample, score_result: ObservationScoreResult
    ) -> None:
        timestamp = sample.utc_time.timestamp()
        self.timestamps.append(timestamp)
        self.azimuths.append(sample.az_deg)
        self.elevations.append(sample.el_deg)
        self.observation_scores.append(float(score_result.score))
        self.weather_scores.append(
            100.0 * float(score_result.subscores.get("weather", 0.0))
        )
        self.az_curve.setData(list(self.timestamps), list(self.azimuths))
        self.el_curve.setData(list(self.timestamps), list(self.elevations))
        self.score_curve.setData(list(self.timestamps), list(self.observation_scores))
        self.weather_curve.setData(list(self.timestamps), list(self.weather_scores))
        brushes = [
            pg.mkBrush(self._score_color(score)) for score in self.observation_scores
        ]
        self.score_scatter.setData(
            x=list(self.timestamps),
            y=list(self.observation_scores),
            brush=brushes,
            pen=pg.mkPen("#0f172a", width=0.8),
            size=8,
        )
        weather_brushes = [
            pg.mkBrush(self._score_color(score)) for score in self.weather_scores
        ]
        self.weather_scatter.setData(
            x=list(self.timestamps),
            y=list(self.weather_scores),
            brush=weather_brushes,
            pen=pg.mkPen("#0f172a", width=0.8),
            size=8,
        )

    def _set_error_state(self, message: str) -> None:
        self.state.last_error = message
        self._append_log(f"[ERROR] {message}")
        self._update_status_banner(f"Error: {message}")

    # -----------------------------------------------------------------
    # Sky projection and prediction/weather refresh logic
    # -----------------------------------------------------------------
    def _init_sky_projection_plot(self) -> None:
        """Initialise all plot widgets and their data/cursor items."""
        self.sky_plot = pg.PlotWidget()
        self.sky_plot.setObjectName("skyPlot")
        self.sky_plot.setBackground("#07111f")
        self.sky_plot.hideAxis("left")
        self.sky_plot.hideAxis("bottom")
        self.sky_plot.setAspectLocked(True)
        self.sky_plot.setMouseEnabled(x=False, y=False)
        self.sky_plot.setXRange(-1.1, 1.1)
        self.sky_plot.setYRange(-1.1, 1.1)
        self.sky_plot.setMinimumHeight(250)
        self.sky_plot.setMaximumHeight(250)
        self.sky_plot.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        ring_angles = [math.radians(deg) for deg in range(361)]
        base_pen = pg.mkPen("#334155", width=1)
        horizon_pen = pg.mkPen("#94a3b8", width=1.4)
        # Concentric circles representing 0°, 30° and 60° altitude.
        for radius, pen in (
            (1.0, horizon_pen),
            (2.0 / 3.0, base_pen),
            (1.0 / 3.0, base_pen),
        ):
            xs = [radius * math.cos(angle) for angle in ring_angles]
            ys = [radius * math.sin(angle) for angle in ring_angles]
            self.sky_plot.plot(xs, ys, pen=pen)
        # Crosshair lines
        self.sky_plot.plot([-1.0, 1.0], [0.0, 0.0], pen=base_pen)
        self.sky_plot.plot([0.0, 0.0], [-1.0, 1.0], pen=base_pen)
        # Cardinal direction labels and altitude labels.
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
        # Plot objects for the live track and predicted trajectory.
        self.sky_track_curve = self.sky_plot.plot(pen=pg.mkPen("#38bdf8", width=1.5))
        self.sky_prediction_curve = self.sky_plot.plot(
            pen=pg.mkPen("#22c55e", width=2, style=Qt.PenStyle.DashLine)
        )
        # Marker for the current/predicted target position.
        self.sky_target_marker = pg.ScatterPlotItem(
            size=13, brush=pg.mkBrush("#f59e0b"), pen=pg.mkPen("#fbbf24", width=2)
        )
        self.sky_plot.addItem(self.sky_target_marker)
        self.sky_target_text = pg.TextItem("", color="#fbbf24", anchor=(0.5, 1.3))
        self.sky_plot.addItem(self.sky_target_text)

        self.elevation_plot = pg.PlotWidget(
            axisItems={"bottom": pg.DateAxisItem(orientation="bottom")}
        )
        self.elevation_plot.setBackground("#07111f")
        self.elevation_plot.showGrid(x=True, y=True, alpha=0.18)
        self.elevation_plot.addLegend(offset=(12, 8))
        self.elevation_plot.setLabel("left", "Elevation (deg)")
        self.elevation_plot.setLabel("bottom", "UTC time")
        self.elevation_plot.setYRange(-90.0, 90.0)
        self.elevation_plot.setMouseEnabled(x=True, y=False)
        self.elevation_plot.enableAutoRange(x=True, y=False)
        self.elevation_plot.setLimits(
            yMin=-90.0, yMax=90.0, minYRange=180.0, maxYRange=180.0
        )
        self.elevation_plot.setMinimumHeight(150)
        self.elevation_plot.setMaximumHeight(150)
        self.elevation_plot.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.el_curve = self.elevation_plot.plot(
            pen=pg.mkPen("#fbbf24", width=2.2), name="Elevation"
        )
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

        self.azimuth_plot = pg.PlotWidget(
            axisItems={"bottom": pg.DateAxisItem(orientation="bottom")}
        )
        self.azimuth_plot.setBackground("#07111f")
        self.azimuth_plot.showGrid(x=True, y=True, alpha=0.18)
        self.azimuth_plot.addLegend(offset=(12, 8))
        self.azimuth_plot.setLabel("left", "Azimuth (deg)")
        self.azimuth_plot.setLabel("bottom", "UTC time")
        self.azimuth_plot.setYRange(0.0, 360.0)
        self.azimuth_plot.setMouseEnabled(x=True, y=False)
        self.azimuth_plot.enableAutoRange(x=True, y=False)
        self.azimuth_plot.setLimits(
            yMin=0.0, yMax=360.0, minYRange=360.0, maxYRange=360.0
        )
        self.azimuth_plot.setMinimumHeight(150)
        self.azimuth_plot.setMaximumHeight(150)
        self.azimuth_plot.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.az_curve = self.azimuth_plot.plot(
            pen=pg.mkPen("#7dd3fc", width=2.2), name="Azimuth"
        )
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

        self.score_plot = pg.PlotWidget(
            axisItems={"bottom": pg.DateAxisItem(orientation="bottom")}
        )
        self.score_plot.setBackground("#07111f")
        self.score_plot.showGrid(x=True, y=True, alpha=0.18)
        self.score_plot.setLabel("left", "Observation Score")
        self.score_plot.setLabel("bottom", "UTC time")
        self.score_plot.setYRange(0.0, 100.0)
        self.score_plot.setMouseEnabled(x=True, y=False)
        self.score_plot.enableAutoRange(x=True, y=False)
        self.score_plot.setLimits(
            yMin=0.0, yMax=100.0, minYRange=100.0, maxYRange=100.0
        )
        self.score_plot.setMinimumHeight(130)
        self.score_plot.setMaximumHeight(130)
        self.score_plot.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.score_curve = self.score_plot.plot(
            pen=pg.mkPen("#94a3b8", width=1.4), name="Score"
        )
        self.score_prediction_curve = self.score_plot.plot(
            pen=pg.mkPen("#60a5fa", width=1.8, style=Qt.PenStyle.DashLine),
            name="Score Forecast",
        )
        self.score_scatter = pg.ScatterPlotItem(size=8, hoverable=True)
        self.score_plot.addItem(self.score_scatter)
        self.score_prediction_scatter = pg.ScatterPlotItem(size=7, hoverable=True)
        self.score_plot.addItem(self.score_prediction_scatter)
        self.score_cursor = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen("#22c55e", width=1.1, style=Qt.PenStyle.DashLine),
        )
        self.score_cursor.setVisible(False)
        self.score_plot.addItem(self.score_cursor)
        self.score_plot.setXLink(self.elevation_plot)

        self.weather_plot = pg.PlotWidget(
            axisItems={"bottom": pg.DateAxisItem(orientation="bottom")}
        )
        self.weather_plot.setBackground("#07111f")
        self.weather_plot.showGrid(x=True, y=True, alpha=0.18)
        self.weather_plot.setLabel("left", "Weather Score")
        self.weather_plot.setLabel("bottom", "UTC time")
        self.weather_plot.setYRange(0.0, 100.0)
        self.weather_plot.setMouseEnabled(x=True, y=False)
        self.weather_plot.enableAutoRange(x=True, y=False)
        self.weather_plot.setLimits(
            yMin=0.0, yMax=100.0, minYRange=100.0, maxYRange=100.0
        )
        self.weather_plot.setMinimumHeight(120)
        self.weather_plot.setMaximumHeight(120)
        self.weather_plot.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.weather_curve = self.weather_plot.plot(
            pen=pg.mkPen("#38bdf8", width=1.4), name="Weather"
        )
        self.weather_prediction_curve = self.weather_plot.plot(
            pen=pg.mkPen("#22d3ee", width=1.8, style=Qt.PenStyle.DashLine),
            name="Weather Forecast",
        )
        self.weather_scatter = pg.ScatterPlotItem(size=8, hoverable=True)
        self.weather_plot.addItem(self.weather_scatter)
        self.weather_prediction_scatter = pg.ScatterPlotItem(size=7, hoverable=True)
        self.weather_plot.addItem(self.weather_prediction_scatter)
        self.weather_cursor = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen("#22c55e", width=1.1, style=Qt.PenStyle.DashLine),
        )
        self.weather_cursor.setVisible(False)
        self.weather_plot.addItem(self.weather_cursor)
        self.weather_plot.setXLink(self.elevation_plot)

        self._set_initial_plot_time_window()

    def _sky_xy_from_altaz(self, az_deg: float, el_deg: float) -> tuple[float, float]:
        """Convert azimuth/elevation into X/Y coordinates for sky projection."""
        clamped_el = max(-90.0, min(90.0, el_deg))
        radius = (90.0 - clamped_el) / 90.0
        radius = max(0.0, min(1.0, radius))
        az_rad = math.radians(az_deg)
        x = radius * math.sin(az_rad)
        y = radius * math.cos(az_rad)
        return x, y

    def _update_sky_projection(self, sample: EphemerisSample) -> None:
        """Update the sky projection trail and marker based on live and predicted samples."""
        # Draw the recent trail of positions on the sky (last ~60 samples)
        trail_points = list(zip(self.azimuths, self.elevations))[-60:]
        xs: list[float] = []
        ys: list[float] = []
        for az_deg, el_deg in trail_points:
            x, y = self._sky_xy_from_altaz(az_deg, el_deg)
            xs.append(x)
            ys.append(y)
        self.sky_track_curve.setData(xs, ys)
        # Draw the predicted future positions if available.
        predicted_xy = [
            self._sky_xy_from_altaz(row.az_deg, row.el_deg)
            for row in self.predicted_samples
        ]
        pred_xs = [point[0] for point in predicted_xy]
        pred_ys = [point[1] for point in predicted_xy]
        self.sky_prediction_curve.setData(pred_xs, pred_ys)
        # Choose whether to display the live sample or a preview sample.
        display_sample = sample
        marker_label_prefix = "LIVE"
        marker_color = "#22c55e" if sample.el_deg > 0 else "#ef4444"
        if not self.follow_live_projection and self.predicted_samples:
            offset_minutes = int(self.timeline_slider.value())
            prediction_index = min(
                len(self.predicted_samples) - 1,
                offset_minutes // self.prediction_step_minutes,
            )
            display_sample = self.predicted_samples[prediction_index]
            marker_label_prefix = f"T+{offset_minutes}m"
            marker_color = "#38bdf8"
        # Update the marker position and annotation.
        marker_x, marker_y = self._sky_xy_from_altaz(
            display_sample.az_deg, display_sample.el_deg
        )
        self.sky_target_marker.setData(
            [marker_x], [marker_y], brush=pg.mkBrush(marker_color)
        )
        self.sky_target_text.setText(
            f"{marker_label_prefix} | Az {display_sample.az_deg:.1f}\N{DEGREE SIGN} | El {display_sample.el_deg:.1f}\N{DEGREE SIGN}"
        )
        self.sky_target_text.setPos(marker_x, marker_y)

    def _should_refresh_prediction(self, sample: EphemerisSample) -> bool:
        """Return True if a new prediction trajectory should be requested."""
        if self.last_prediction_anchor_utc is None:
            return True
        elapsed = (sample.utc_time - self.last_prediction_anchor_utc).total_seconds()
        return elapsed >= self.prediction_refresh_seconds

    def _should_refresh_weather(self, sample: EphemerisSample) -> bool:
        """Return True if a new weather update should be requested."""
        if self.last_weather_update_utc is None:
            return True
        elapsed = (sample.utc_time - self.last_weather_update_utc).total_seconds()
        return elapsed >= self.weather_refresh_seconds

    def _request_weather_update(self, anchor_time: datetime) -> None:
        """Dispatch a request to update weather information from the weather API."""
        _ = anchor_time  # anchor_time is unused but kept for API symmetry
        if self.weather_request_thread and self.weather_request_thread.isRunning():
            return
        location = self.state.location

        def action() -> tuple[
            dict[str, float | None], dict[datetime, dict[str, float | None]]
        ]:
            return self.fetcher.fetch_open_meteo_weather(location)

        thread = RequestThread(action, self)
        self.weather_request_thread = thread
        thread.result_ready.connect(self._handle_weather_result)
        thread.error_occurred.connect(self._handle_weather_error)
        thread.start()

    def _request_prediction_trajectory(self, anchor_time: datetime) -> None:
        """Dispatch a request to compute a future ephemeris trajectory."""
        if (
            self.prediction_request_thread
            and self.prediction_request_thread.isRunning()
        ):
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
        """Handle the response from a prediction trajectory request."""
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
        self.timeline_slider.setRange(
            0, max(0, (len(rows) - 1) * self.prediction_step_minutes)
        )
        self.back_to_live_button.setEnabled(not self.follow_live_projection)
        if self.state.latest_sample:
            self._update_sky_projection(self.state.latest_sample)
        self._append_log(
            f"Prediction refreshed: {len(rows)} samples for the next {self.prediction_horizon_minutes // 60}h."
        )

    @Slot(str)
    def _handle_prediction_error(self, message: str) -> None:
        """Handle errors that occur during prediction requests."""
        self._append_log(f"[WARN] Prediction update failed: {message}")

    @Slot(object)
    def _handle_weather_result(self, payload: object) -> None:
        """Handle the response from a weather update request."""
        if isinstance(payload, tuple) and len(payload) == 2:
            current_weather, hourly_forecast = payload
            self.latest_weather = {
                k: float(v) if v is not None else None
                for k, v in current_weather.items()
            }
            self.hourly_forecast = {
                t: {k: float(wv) if wv is not None else None for k, wv in w.items()}
                for t, w in hourly_forecast.items()
            }
        elif isinstance(payload, dict):
            self.latest_weather = {
                k: float(v) if v is not None else None for k, v in payload.items()
            }
            self.hourly_forecast.clear()
        else:
            self._append_log("[WARN] Unexpected weather payload.")
            return
        self.last_weather_update_utc = datetime.now(timezone.utc)
        cloud = self.latest_weather.get("cloud_cover")
        humidity = self.latest_weather.get("humidity")
        visibility = self.latest_weather.get("visibility_km")
        wind = self.latest_weather.get("wind_speed")
        self._append_log(
            "Weather updated (Open-Meteo): "
            f"cloud={cloud if cloud is not None else '-'}%, "
            f"humidity={humidity if humidity is not None else '-'}%, "
            f"visibility={visibility if visibility is not None else '-'}km, "
            f"wind={wind if wind is not None else '-'}  "
            f"forecast={len(self.hourly_forecast)}h"
        )
        # Recompute displayed and forecast scores with fresh weather values.
        if self.state.latest_sample is not None:
            if self.follow_live_projection:
                updated_result = self._evaluate_observation(self.state.latest_sample)
                self._render_sample_fields(self.state.latest_sample, updated_result)
            self._update_prediction_plot_curves()

    @Slot(str)
    def _handle_weather_error(self, message: str) -> None:
        """Handle errors that occur during weather update requests."""
        self._append_log(f"[WARN] Weather update failed (Open-Meteo): {message}")

    # -----------------------------------------------------------------
    # Location/IP and tracking actions
    # -----------------------------------------------------------------
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
            self._append_log(
                f"IP location loaded: {label} ({location.latitude_deg:.6f}, {location.longitude_deg:.6f})"
            )
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
        # Reset prediction/weather state when tracking starts.
        self.predicted_samples.clear()
        self.predicted_observation_scores.clear()
        self.predicted_weather_scores.clear()
        self.weather_scores.clear()
        self.last_prediction_anchor_utc = None
        self.last_weather_update_utc = None
        self.latest_weather = None
        self.follow_live_projection = True
        self.timeline_status_label.setText("LIVE")
        self.timeline_slider.setValue(0)
        self.timeline_slider.setRange(0, self.prediction_horizon_minutes)
        self.back_to_live_button.setEnabled(False)
        self.sky_prediction_curve.setData([], [])
        self._update_prediction_plot_curves()
        self._append_log(
            f"Tracking started for lat={location.latitude_deg:.6f}, lon={location.longitude_deg:.6f}, "
            f"elev={location.elevation_km:.3f} km, interval={interval_sec}s"
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
        """Ensure background threads are stopped before closing the window."""
        if self.tracking_thread and self.tracking_thread.isRunning():
            self.tracking_thread.request_stop()
            self.tracking_thread.wait(5000)
        event.accept()


def run_app(
    state: TrackerState | None = None, config: TrackerAppConfig | None = None
) -> int:
    """Run the astronomy tracker application."""
    import sys

    app_config = config or TrackerAppConfig()
    app = QApplication(sys.argv)
    app.setApplicationName(app_config.app_name)
    app.setOrganizationName(app_config.organization_name)
    # Load a rounded version of the application icon if available.
    icon_path = Path(__file__).resolve().parent / "static" / "solar_system.jpg"
    rounded_icon = _build_rounded_icon(icon_path)
    if rounded_icon is not None and not rounded_icon.isNull():
        app.setWindowIcon(rounded_icon)
    window = AstronomyTrackerWindow(state=state, config=app_config)
    if rounded_icon is not None and not rounded_icon.isNull():
        window.setWindowIcon(rounded_icon)
    window.show()
    return app.exec()


def _build_rounded_icon(
    icon_path: Path, size: int = 256, corner_ratio: float = 0.22
) -> QIcon | None:
    """Helper to load and round a square image into a QIcon."""
    if not icon_path.exists():
        return None
    source = QPixmap(str(icon_path))
    if source.isNull():
        return None
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
    painter.drawPixmap(
        (size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled
    )
    painter.end()
    return QIcon(rounded)
