from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PySide6.QtGui import QBrush
from PySide6.QtCore import Qt

from astronomy.gui import AstronomyTrackerWindow
from astronomy.tracker_state import EphemerisSample, TrackerState


def _sample(index: int, *, az: float, el: float) -> EphemerisSample:
    utc = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
    return EphemerisSample(
        utc_time=utc,
        local_time=utc,
        ra_deg=float(index),
        dec_deg=float(index),
        az_deg=az,
        el_deg=el,
        solar_elong_deg=30.0,
        compass_direction="N",
        visibility_status="Above horizon",
        range_au=1.0,
        range_rate_kms=0.0,
        solar_presence="",
        interferer_presence="",
        solar_alignment_code="",
    )


class _Curve:
    def __init__(self) -> None:
        self.data = None

    def setData(self, *args, **kwargs) -> None:
        self.data = (args, kwargs)


class _Marker(_Curve):
    pass


class _Text:
    def __init__(self) -> None:
        self.text = ""
        self.pos = None

    def setText(self, text: str) -> None:
        self.text = text

    def setPos(self, *pos) -> None:
        self.pos = pos


class _Slider:
    def __init__(self, value: int) -> None:
        self._value = value

    def value(self) -> int:
        return self._value


def test_update_sky_projection_uses_history_for_negative_offset() -> None:
    latest = _sample(10, az=0.0, el=10.0)
    history = [_sample(0, az=90.0, el=30.0), _sample(5, az=180.0, el=40.0)]
    prediction = [_sample(15, az=270.0, el=50.0)]
    fake = type("FakeWindow", (), {})()
    fake.azimuths = []
    fake.elevations = []
    fake.predicted_samples = prediction
    fake.history_24hr_samples = history
    fake.history_step_minutes = 5
    fake.prediction_step_minutes = 5
    fake.timeline_slider = _Slider(-5)
    fake.sky_track_curve = _Curve()
    fake.sky_prediction_curve = _Curve()
    fake.sky_history_curve = _Curve()
    fake.sky_target_marker = _Marker()
    fake.sky_target_text = _Text()
    fake._sky_xy_from_altaz = AstronomyTrackerWindow._sky_xy_from_altaz.__get__(fake)
    fake._current_timeline_selection = (
        AstronomyTrackerWindow._current_timeline_selection.__get__(fake)
    )

    AstronomyTrackerWindow._update_sky_projection(fake, latest)

    expected_x, expected_y = fake._sky_xy_from_altaz(history[0].az_deg, history[0].el_deg)
    marker_args, marker_kwargs = fake.sky_target_marker.data
    assert marker_args == ([expected_x], [expected_y])
    assert isinstance(marker_kwargs["brush"], QBrush)
    assert fake.sky_target_text.text.startswith("T-5m")


class _FakeRequestThread:
    def __init__(self, running: bool) -> None:
        self._running = running
        self.interrupted = False
        self.waited: list[int] = []
        self.result_ready = _FakeSignal()
        self.error_occurred = _FakeSignal()
        self.finished = _FakeSignal()

    def isRunning(self) -> bool:
        return self._running

    def requestInterruption(self) -> None:
        self.interrupted = True

    def wait(self, timeout_ms: int) -> None:
        self.waited.append(timeout_ms)


class _FakeSignal:
    def __init__(self) -> None:
        self.disconnected = False

    def disconnect(self) -> None:
        self.disconnected = True


def test_stop_request_threads_disconnects_and_waits_running_threads() -> None:
    running = _FakeRequestThread(True)
    stopped = _FakeRequestThread(False)
    fake = type("FakeWindow", (), {})()
    fake.pending_request_thread = running
    fake.prediction_request_thread = stopped
    fake.history_request_thread = None
    fake.weather_request_thread = None
    fake._request_threads = AstronomyTrackerWindow._request_threads.__get__(fake)
    fake._disconnect_request_thread = (
        AstronomyTrackerWindow._disconnect_request_thread.__get__(fake)
    )

    AstronomyTrackerWindow._stop_request_threads(fake, timeout_ms=123)

    assert running.result_ready.disconnected is True
    assert running.error_occurred.disconnected is True
    assert running.finished.disconnected is True
    assert running.interrupted is True
    assert running.waited == [123]
    assert stopped.result_ready.disconnected is True
    assert stopped.waited == []


class _FakeWheelEvent:
    def __init__(self, modifiers) -> None:
        self._modifiers = modifiers
        self.ignored = False

    def modifiers(self):
        return self._modifiers

    def ignore(self) -> None:
        self.ignored = True


class _FakeViewBox:
    def __init__(self) -> None:
        self.original_calls = 0

    def wheelEvent(self, event, axis=None) -> None:  # noqa: N802
        self.original_calls += 1


class _FakePlot:
    def __init__(self) -> None:
        self.view_box = _FakeViewBox()

    def getViewBox(self) -> _FakeViewBox:  # noqa: N802
        return self.view_box


def test_plot_wheel_zoom_requires_control_or_command_modifier() -> None:
    plot = _FakePlot()
    fake = type("FakeWindow", (), {})()

    AstronomyTrackerWindow._disable_plot_wheel_zoom(fake, plot)

    plain_event = _FakeWheelEvent(Qt.KeyboardModifier.NoModifier)
    shift_event = _FakeWheelEvent(Qt.KeyboardModifier.ShiftModifier)
    control_event = _FakeWheelEvent(Qt.KeyboardModifier.ControlModifier)
    command_event = _FakeWheelEvent(Qt.KeyboardModifier.MetaModifier)
    plot.view_box.wheelEvent(plain_event)
    plot.view_box.wheelEvent(shift_event)
    plot.view_box.wheelEvent(control_event)
    plot.view_box.wheelEvent(command_event)

    assert plain_event.ignored is True
    assert shift_event.ignored is True
    assert control_event.ignored is False
    assert command_event.ignored is False
    assert plot.view_box.original_calls == 2


class _RangePlot:
    """Minimal stand-in for the elevation PlotWidget's x-range interface."""

    def __init__(self, x_min: float = 0.0, x_max: float = 3600.0) -> None:
        self.x_range = (x_min, x_max)
        self.padding_used: list[float | None] = []

    def getViewBox(self):
        return self

    def viewRange(self):
        return [list(self.x_range), [-90.0, 90.0]]

    def setXRange(self, x_min: float, x_max: float, padding=None) -> None:
        self.x_range = (x_min, x_max)
        self.padding_used.append(padding)


def _centering_window(x_min: float, x_max: float):
    fake = type("FakeWindow", (), {})()
    fake.elevation_plot = _RangePlot(x_min, x_max)
    fake.plot_window_minutes = 60
    fake._centered_timestamp = None
    fake._center_plot_window = AstronomyTrackerWindow._center_plot_window.__get__(fake)
    return fake


def test_center_plot_window_puts_the_moment_in_the_middle() -> None:
    fake = _centering_window(0.0, 3600.0)

    fake._center_plot_window(1_000_000.0)

    x_min, x_max = fake.elevation_plot.x_range
    assert (x_min + x_max) / 2 == 1_000_000.0
    # Padding must be suppressed or pyqtgraph widens the range and the moment
    # stops being centred.
    assert fake.elevation_plot.padding_used == [0]


def test_center_plot_window_preserves_the_zoom_the_user_chose() -> None:
    # A six-hour view stays six hours wide when it slides to a new moment.
    fake = _centering_window(0.0, 6 * 3600.0)

    fake._center_plot_window(1_000_000.0)

    x_min, x_max = fake.elevation_plot.x_range
    assert x_max - x_min == 6 * 3600.0
    assert (x_min + x_max) / 2 == 1_000_000.0


def test_center_plot_window_is_unaffected_by_a_long_forecast() -> None:
    # The regression this guards: a forecast running weeks ahead used to drag
    # the auto-ranged x axis with it, shrinking the live trace to a sliver.
    fake = _centering_window(0.0, 3600.0)
    live = 1_000_000.0

    fake._center_plot_window(live)
    x_min, x_max = fake.elevation_plot.x_range

    assert x_max - x_min == 3600.0
    assert x_min < live < x_max


def test_center_plot_window_falls_back_on_a_degenerate_range() -> None:
    for x_min, x_max in ((5.0, 5.0), (10.0, 0.0), (float("nan"), float("nan"))):
        fake = _centering_window(x_min, x_max)
        fake._center_plot_window(1_000_000.0)
        span_min, span_max = fake.elevation_plot.x_range
        assert span_max - span_min == 60 * 60.0
        assert (span_min + span_max) / 2 == 1_000_000.0


def test_reset_plot_time_window_returns_to_the_default_span() -> None:
    fake = _centering_window(0.0, 6 * 3600.0)
    fake._reset_plot_time_window = AstronomyTrackerWindow._reset_plot_time_window.__get__(
        fake
    )

    fake._center_plot_window(1_000_000.0)
    assert fake._centered_timestamp == 1_000_000.0

    fake._reset_plot_time_window()
    x_min, x_max = fake.elevation_plot.x_range
    assert x_max - x_min == 60 * 60.0
    # Reset changes the span but keeps looking at the same moment.
    assert (x_min + x_max) / 2 == 1_000_000.0
