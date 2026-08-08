from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from astronomy.api_fetcher import HorizonsFetcher
from astronomy.forecast import (
    BASE_STEP_MINUTES,
    DEFAULT_HORIZON_MINUTES,
    FORECAST_HORIZONS,
    format_duration,
    horizon_index,
    refresh_seconds_for_horizon,
    step_for_horizon,
)
from astronomy.gui import AstronomyTrackerWindow
from astronomy.meteor_fetcher import MeteorRadiantFetcher

DAY = 24 * 60


def test_horizon_options_are_sorted_and_include_the_default() -> None:
    minutes = [m for _, m in FORECAST_HORIZONS]
    assert minutes == sorted(minutes)
    assert DEFAULT_HORIZON_MINUTES in minutes


def test_step_never_goes_below_the_base_interval() -> None:
    for _, minutes in FORECAST_HORIZONS:
        assert step_for_horizon(minutes, 100_000) == BASE_STEP_MINUTES
    assert step_for_horizon(0, 500) == BASE_STEP_MINUTES


def test_step_keeps_every_horizon_within_the_sample_budget() -> None:
    for budget in (HorizonsFetcher.MAX_RANGE_SAMPLES, MeteorRadiantFetcher.MAX_RANGE_SAMPLES):
        for _, minutes in FORECAST_HORIZONS:
            step = step_for_horizon(minutes, budget)
            samples = minutes // step + 1
            assert samples <= budget + 1


def test_a_network_provider_coarsens_where_a_local_one_does_not() -> None:
    # Seven days is the interesting case: Horizons has to widen its step, while
    # locally computed radiants keep full resolution.
    week = 7 * DAY
    assert step_for_horizon(week, HorizonsFetcher.MAX_RANGE_SAMPLES) > BASE_STEP_MINUTES
    assert (
        step_for_horizon(week, MeteorRadiantFetcher.MAX_RANGE_SAMPLES)
        == BASE_STEP_MINUTES
    )


def test_step_grows_monotonically_with_the_horizon() -> None:
    steps = [step_for_horizon(m, 500) for _, m in FORECAST_HORIZONS]
    assert steps == sorted(steps)


def test_refresh_cadence_stretches_with_the_horizon() -> None:
    # The 24-hour default keeps its historical five-minute cadence.
    assert refresh_seconds_for_horizon(DEFAULT_HORIZON_MINUTES) == 300
    # Shorter horizons are not refreshed more aggressively than that.
    assert refresh_seconds_for_horizon(6 * 60) == 300
    assert refresh_seconds_for_horizon(7 * DAY) == 2100
    assert refresh_seconds_for_horizon(30 * DAY) == 9000


def test_horizon_index_snaps_to_the_nearest_option() -> None:
    assert FORECAST_HORIZONS[horizon_index(DEFAULT_HORIZON_MINUTES)][1] == DAY
    assert FORECAST_HORIZONS[horizon_index(7 * DAY)][1] == 7 * DAY
    # An unlisted value picks its closest neighbour rather than failing.
    assert FORECAST_HORIZONS[horizon_index(8 * DAY)][1] == 7 * DAY


@pytest.mark.parametrize(
    "minutes,expected",
    [(30, "30min"), (6 * 60, "6h"), (DAY, "1d"), (7 * DAY, "7d"), (36 * 60, "36h")],
)
def test_format_duration(minutes: int, expected: str) -> None:
    assert format_duration(minutes) == expected


def _window_with_provider(provider):
    fake = type("FakeWindow", (), {})()
    fake.fetcher_factory = provider
    fake._max_prediction_samples = AstronomyTrackerWindow._max_prediction_samples.__get__(
        fake
    )
    fake._step_for_horizon = AstronomyTrackerWindow._step_for_horizon.__get__(fake)
    return fake


def test_window_reads_the_sample_budget_from_its_provider() -> None:
    assert (
        _window_with_provider(MeteorRadiantFetcher)._max_prediction_samples()
        == MeteorRadiantFetcher.MAX_RANGE_SAMPLES
    )
    assert (
        _window_with_provider(HorizonsFetcher)._max_prediction_samples()
        == HorizonsFetcher.MAX_RANGE_SAMPLES
    )
    # A provider that declares no budget falls back to the conservative one.
    assert (
        _window_with_provider(lambda: None)._max_prediction_samples()
        == HorizonsFetcher.MAX_RANGE_SAMPLES
    )


def test_changing_horizon_discards_the_trajectory_built_for_the_old_one() -> None:
    fake = _window_with_provider(MeteorRadiantFetcher)
    fake.prediction_horizon_minutes = DAY
    fake.prediction_step_minutes = 5
    fake.prediction_refresh_seconds = 300
    fake.predicted_samples = ["stale"] * 289
    fake.predicted_observation_scores = [1.0] * 289
    fake.predicted_weather_scores = [1.0] * 289
    fake.last_prediction_anchor_utc = datetime(2026, 8, 8, tzinfo=timezone.utc)
    fake.state = type("S", (), {"latest_sample": None})()
    fake.logged: list[str] = []
    fake.synced = 0
    fake.requested: list[datetime] = []
    fake._append_log = fake.logged.append
    fake._sync_timeline_range = lambda: setattr(fake, "synced", fake.synced + 1)
    fake._request_prediction_trajectory = fake.requested.append
    fake._refresh_for_horizon = AstronomyTrackerWindow._refresh_for_horizon.__get__(fake)

    apply_horizon = AstronomyTrackerWindow._apply_forecast_horizon.__get__(fake)
    apply_horizon(7 * DAY)

    assert fake.prediction_horizon_minutes == 7 * DAY
    assert fake.prediction_refresh_seconds == 2100
    # Samples spaced for the old horizon would be indexed wrongly by the
    # timeline, so they must not survive the switch.
    assert fake.predicted_samples == []
    assert fake.predicted_observation_scores == []
    assert fake.last_prediction_anchor_utc is None
    assert fake.synced == 1
    assert len(fake.requested) == 1
    assert "7d" in fake.logged[0]


def test_reselecting_the_current_horizon_is_a_no_op() -> None:
    fake = _window_with_provider(MeteorRadiantFetcher)
    fake.prediction_horizon_minutes = DAY
    fake.predicted_samples = ["keep"]
    fake._request_prediction_trajectory = lambda _: pytest.fail("should not re-request")

    AstronomyTrackerWindow._apply_forecast_horizon.__get__(fake)(DAY)
    assert fake.predicted_samples == ["keep"]


def _weather_window(forecast_hours: int):
    fake = type("FakeWindow", (), {})()
    base = datetime(2026, 8, 8, tzinfo=timezone.utc)
    fake.hourly_forecast = {
        base + timedelta(hours=i): {"cloud_cover": 90.0} for i in range(forecast_hours)
    }
    fake.latest_weather = {"cloud_cover": 95.0}
    fake._weather_for_time = AstronomyTrackerWindow._weather_for_time.__get__(fake)
    return fake, base


def test_weather_inside_the_forecast_range_is_used() -> None:
    fake, base = _weather_window(48)
    assert fake._weather_for_time(base + timedelta(hours=5))["cloud_cover"] == 90.0


def test_weather_beyond_the_forecast_falls_back_to_neutral_defaults() -> None:
    # Open-Meteo reaches 16 days; a 30-day forecast runs past it. Scoring those
    # samples with today's cloud cover would be worse than not scoring weather.
    fake, base = _weather_window(48)
    assert fake._weather_for_time(base + timedelta(days=20)) == {}
    assert fake._weather_for_time(base - timedelta(days=5)) == {}


def test_weather_without_any_forecast_still_uses_current_conditions() -> None:
    fake = type("FakeWindow", (), {})()
    fake.hourly_forecast = {}
    fake.latest_weather = {"cloud_cover": 95.0}
    fake._weather_for_time = AstronomyTrackerWindow._weather_for_time.__get__(fake)
    assert fake._weather_for_time(datetime(2026, 8, 8, tzinfo=timezone.utc)) == {
        "cloud_cover": 95.0
    }
