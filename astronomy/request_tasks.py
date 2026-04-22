from __future__ import annotations

from datetime import datetime

from astronomy.api_fetcher import HorizonsFetcher
from astronomy.tracker_state import EphemerisSample, ObserverLocation


def fetch_current_ephemeris_task(
    target_command: str,
    location: ObserverLocation,
    observation_time: datetime | None = None,
) -> EphemerisSample:
    return HorizonsFetcher().fetch_current_ephemeris(
        target_command=target_command,
        location=location,
        observation_time=observation_time,
    )


def fetch_ephemeris_range_task(
    *,
    target_command: str,
    location: ObserverLocation,
    start_time: datetime,
    stop_time: datetime,
    step_minutes: int,
) -> list[EphemerisSample]:
    return HorizonsFetcher().fetch_ephemeris_range(
        target_command=target_command,
        location=location,
        start_time=start_time,
        stop_time=stop_time,
        step_minutes=step_minutes,
    )


def fetch_ip_location_task() -> tuple[ObserverLocation, str]:
    return HorizonsFetcher().fetch_ip_location()


def fetch_open_meteo_weather_task(
    location: ObserverLocation,
) -> tuple[dict[str, float | None], dict[datetime, dict[str, float | None]]]:
    return HorizonsFetcher().fetch_open_meteo_weather(location)
