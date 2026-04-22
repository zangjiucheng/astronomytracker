from __future__ import annotations

from datetime import datetime, timezone

from astronomy import request_tasks
from astronomy.tracker_state import ObserverLocation


class _FakeFetcher:
    instances: list["_FakeFetcher"] = []

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.instances.append(self)

    def fetch_current_ephemeris(
        self,
        target_command: str,
        location: ObserverLocation,
        observation_time: datetime | None = None,
    ) -> str:
        self.calls.append("current")
        return f"{target_command}:{location.latitude_deg}:{observation_time is not None}"

    def fetch_ephemeris_range(
        self,
        target_command: str,
        location: ObserverLocation,
        start_time: datetime,
        stop_time: datetime,
        step_minutes: int,
    ) -> list[str]:
        self.calls.append("range")
        return [f"{target_command}:{step_minutes}:{start_time < stop_time}"]

    def fetch_ip_location(self) -> tuple[ObserverLocation, str]:
        self.calls.append("ip")
        return ObserverLocation(1.0, 2.0, 0.0), "Test"

    def fetch_open_meteo_weather(
        self, location: ObserverLocation
    ) -> tuple[dict[str, float | None], dict[datetime, dict[str, float | None]]]:
        self.calls.append("weather")
        return {"cloud_cover": 0.0}, {}


def test_request_tasks_create_independent_fetchers(monkeypatch) -> None:
    _FakeFetcher.instances = []
    monkeypatch.setattr(request_tasks, "HorizonsFetcher", _FakeFetcher)
    location = ObserverLocation(43.0, -80.0, 0.1)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    stop = datetime(2026, 1, 2, tzinfo=timezone.utc)

    request_tasks.fetch_current_ephemeris_task("'301'", location, start)
    request_tasks.fetch_ephemeris_range_task(
        target_command="'301'",
        location=location,
        start_time=start,
        stop_time=stop,
        step_minutes=5,
    )
    request_tasks.fetch_ip_location_task()
    request_tasks.fetch_open_meteo_weather_task(location)

    assert len(_FakeFetcher.instances) == 4
    assert [instance.calls for instance in _FakeFetcher.instances] == [
        ["current"],
        ["range"],
        ["ip"],
        ["weather"],
    ]
