from __future__ import annotations

from datetime import datetime
from typing import Callable

from astronomy.api_fetcher import HorizonsFetcher
from astronomy.tracker_state import EphemerisSample, ObserverLocation

# Any object exposing the HorizonsFetcher ephemeris methods, so targets without
# a Horizons ephemeris can supply their own provider.
FetcherFactory = Callable[[], HorizonsFetcher]


def _resolve(fetcher_factory: FetcherFactory | None) -> HorizonsFetcher:
    # Looked up at call time rather than bound as a default argument so the
    # module attribute stays patchable.
    return (fetcher_factory or HorizonsFetcher)()


def fetch_current_ephemeris_task(
    target_command: str,
    location: ObserverLocation,
    observation_time: datetime | None = None,
    fetcher_factory: FetcherFactory | None = None,
) -> EphemerisSample:
    return _resolve(fetcher_factory).fetch_current_ephemeris(
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
    fetcher_factory: FetcherFactory | None = None,
) -> list[EphemerisSample]:
    return _resolve(fetcher_factory).fetch_ephemeris_range(
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
