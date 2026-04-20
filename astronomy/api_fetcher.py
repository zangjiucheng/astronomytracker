from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

from astronomy.horizons_parser import HorizonsParser
from astronomy.tracker_state import EphemerisSample, HorizonsError, ObserverLocation

API_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
IP_GEO_URL = "https://ipwho.is/"


def build_observer_params(
    target_command: str,
    location: ObserverLocation,
    observation_time: datetime,
) -> dict[str, str]:
    if observation_time.tzinfo is None:
        observation_time = observation_time.replace(tzinfo=timezone.utc)

    utc_time = observation_time.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    east_longitude = location.longitude_deg % 360.0

    return {
        "format": "text",
        "COMMAND": target_command,
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'coord'",
        "COORD_TYPE": "'GEODETIC'",
        "SITE_COORD": f"'{east_longitude:.6f},{location.latitude_deg:.6f},{location.elevation_km:.6f}'",
        "TLIST": f"'{utc_time}'",
        "TLIST_TYPE": "'CAL'",
        "TIME_TYPE": "'UT'",
        "ANG_FORMAT": "'DEG'",
        "APPARENT": "'REFRACTED'",
        "CSV_FORMAT": "'YES'",
        "EXTRA_PREC": "'YES'",
        "QUANTITIES": "'1,4,20,23'",
    }


def build_observer_range_params(
    target_command: str,
    location: ObserverLocation,
    start_time: datetime,
    stop_time: datetime,
    step_minutes: int,
) -> dict[str, str]:
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if stop_time.tzinfo is None:
        stop_time = stop_time.replace(tzinfo=timezone.utc)

    start_utc = start_time.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    stop_utc = stop_time.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    east_longitude = location.longitude_deg % 360.0
    step = max(1, int(step_minutes))

    return {
        "format": "text",
        "COMMAND": target_command,
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'coord'",
        "COORD_TYPE": "'GEODETIC'",
        "SITE_COORD": f"'{east_longitude:.6f},{location.latitude_deg:.6f},{location.elevation_km:.6f}'",
        "START_TIME": f"'{start_utc}'",
        "STOP_TIME": f"'{stop_utc}'",
        "STEP_SIZE": f"'{step} m'",
        "TIME_TYPE": "'UT'",
        "ANG_FORMAT": "'DEG'",
        "APPARENT": "'REFRACTED'",
        "CSV_FORMAT": "'YES'",
        "EXTRA_PREC": "'YES'",
        "QUANTITIES": "'1,4,20,23'",
    }


class HorizonsFetcher:
    def __init__(self, timeout_sec: int = 30, retries: int = 3):
        self.timeout_sec = timeout_sec
        self.retries = retries
        self.session = requests.Session()
        self.parser = HorizonsParser()

    def fetch_current_ephemeris(
        self,
        target_command: str,
        location: ObserverLocation,
        observation_time: datetime | None = None,
    ) -> EphemerisSample:
        if observation_time is None:
            observation_time = datetime.now(timezone.utc)

        last_error: Exception | None = None
        backoff_seconds = 1.0

        for attempt in range(1, self.retries + 1):
            try:
                params = build_observer_params(target_command, location, observation_time)
                response = self.session.get(API_URL, params=params, timeout=self.timeout_sec)
                response.raise_for_status()
                return self.parser.parse(response.text)
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2.0

        assert last_error is not None
        raise HorizonsError(f"Failed to fetch Horizons ephemeris after {self.retries} attempts: {last_error}") from last_error

    def fetch_ephemeris_range(
        self,
        target_command: str,
        location: ObserverLocation,
        start_time: datetime,
        stop_time: datetime,
        step_minutes: int = 1,
    ) -> list[EphemerisSample]:
        last_error: Exception | None = None
        backoff_seconds = 1.0

        for attempt in range(1, self.retries + 1):
            try:
                params = build_observer_range_params(
                    target_command=target_command,
                    location=location,
                    start_time=start_time,
                    stop_time=stop_time,
                    step_minutes=step_minutes,
                )
                response = self.session.get(API_URL, params=params, timeout=self.timeout_sec)
                response.raise_for_status()
                return self.parser.parse_many(response.text)
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2.0

        assert last_error is not None
        raise HorizonsError(
            f"Failed to fetch Horizons range ephemeris after {self.retries} attempts: {last_error}"
        ) from last_error

    def fetch_ip_location(self) -> tuple[ObserverLocation, str]:
        response = self.session.get(IP_GEO_URL, timeout=10)
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise HorizonsError(f"IP geolocation service returned invalid JSON: {exc}") from exc

        if not data.get("success", False):
            message = data.get("message") or data.get("error") or "unknown error"
            raise HorizonsError(f"IP geolocation failed: {message}")

        latitude = data.get("latitude")
        longitude = data.get("longitude")
        if latitude is None or longitude is None:
            raise HorizonsError("IP geolocation response did not include latitude/longitude.")

        location = ObserverLocation(float(latitude), float(longitude), 0.0)
        label = ", ".join(part for part in [data.get("city"), data.get("region"), data.get("country")] if part)
        return location, label
