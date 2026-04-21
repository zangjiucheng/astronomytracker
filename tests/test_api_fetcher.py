from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime, timezone

from astronomy.api_fetcher import build_observer_params, build_observer_range_params
from astronomy.tracker_state import ObserverLocation


def test_build_observer_params() -> None:
    location = ObserverLocation(43.2557, -79.8711, 0.10)
    obs_time = datetime(2025, 4, 21, 22, 0, 0, tzinfo=timezone.utc)

    params = build_observer_params("'301'", location, obs_time)

    assert params["format"] == "text"
    assert params["COMMAND"] == "'301'"
    assert params["CENTER"] == "'coord'"
    assert params["COORD_TYPE"] == "'GEODETIC'"
    assert "SITE_COORD" in params
    assert "TLIST" in params


def test_build_observer_params_normalizes_longitude() -> None:
    location = ObserverLocation(43.2557, 280.0, 0.0)
    obs_time = datetime(2025, 4, 21, 22, 0, 0, tzinfo=timezone.utc)

    params = build_observer_params("'301'", location, obs_time)

    coord = params["SITE_COORD"]
    assert "280.0" in coord or "280.000" in coord


def test_build_observer_range_params() -> None:
    location = ObserverLocation(43.2557, -79.8711, 0.10)
    start = datetime(2025, 4, 21, 20, 0, 0, tzinfo=timezone.utc)
    stop = datetime(2025, 4, 21, 23, 0, 0, tzinfo=timezone.utc)

    params = build_observer_range_params(
        "'301'", location, start, stop, step_minutes=10
    )

    assert "START_TIME" in params
    assert "STOP_TIME" in params
    assert params["STEP_SIZE"] == "'10 m'"


def test_build_observer_range_params_step_minimum_is_one() -> None:
    location = ObserverLocation(43.2557, -79.8711, 0.10)
    start = datetime(2025, 4, 21, 20, 0, 0, tzinfo=timezone.utc)
    stop = datetime(2025, 4, 21, 23, 0, 0, tzinfo=timezone.utc)

    params = build_observer_range_params("'301'", location, start, stop, step_minutes=0)

    assert params["STEP_SIZE"] == "'1 m'"


def test_build_observer_params_adds_tzinfo_if_missing() -> None:
    location = ObserverLocation(43.2557, -79.8711, 0.10)
    obs_time = datetime(2025, 4, 21, 22, 0, 0)

    params = build_observer_params("'301'", location, obs_time)

    assert "TLIST" in params
