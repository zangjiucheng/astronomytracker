from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

from astronomy.horizons_parser import HorizonsParser
from astronomy.tracker_state import EphemerisSample, HorizonsError, ObserverLocation

API_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
IP_GEO_URL = "https://ipwho.is/"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


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

    def fetch_open_meteo_weather(self, location: ObserverLocation) -> dict[str, float | None]:
        params = {
            "latitude": f"{location.latitude_deg:.6f}",
            "longitude": f"{location.longitude_deg:.6f}",
            "timezone": "UTC",
            "current": (
                "temperature_2m,relative_humidity_2m,dew_point_2m,cloud_cover,"
                "wind_speed_10m"
            ),
            "hourly": "visibility",
            "forecast_days": "1",
        }

        response = self.session.get(OPEN_METEO_URL, params=params, timeout=self.timeout_sec)
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise HorizonsError(f"Open-Meteo returned invalid JSON: {exc}") from exc

        current = data.get("current")
        if not isinstance(current, dict):
            raise HorizonsError("Open-Meteo response missing 'current' weather block.")

        hourly = data.get("hourly") if isinstance(data.get("hourly"), dict) else {}
        visibility_series = hourly.get("visibility") if isinstance(hourly, dict) else None
        hourly_times = hourly.get("time") if isinstance(hourly, dict) else None
        visibility_m = None

        if isinstance(visibility_series, list) and isinstance(hourly_times, list):
            try:
                current_time = str(current.get("time", ""))
                current_hour = current_time[:13]  # e.g. 2026-04-21T16
                match_idx = None
                for idx, value in enumerate(hourly_times):
                    if str(value).startswith(current_hour):
                        match_idx = idx
                        break
                if match_idx is None and visibility_series:
                    match_idx = min(len(visibility_series), len(hourly_times)) - 1

                if match_idx is not None and match_idx >= 0 and match_idx < len(visibility_series):
                    visibility_m = float(visibility_series[match_idx])
            except (TypeError, ValueError):
                visibility_m = None
        elif isinstance(visibility_series, list) and visibility_series:
            try:
                visibility_m = float(visibility_series[0])
            except (TypeError, ValueError):
                visibility_m = None

        def _as_float(value: object) -> float | None:
            try:
                if value is None:
                    return None
                return float(value)
            except (TypeError, ValueError):
                return None

        cloud_cover = _as_float(current.get("cloud_cover"))
        humidity = _as_float(current.get("relative_humidity_2m"))
        temperature = _as_float(current.get("temperature_2m"))
        dew_point = _as_float(current.get("dew_point_2m"))
        wind_speed = _as_float(current.get("wind_speed_10m"))

        visibility_km = None if visibility_m is None else max(0.0, visibility_m / 1000.0)
        transparency = None if cloud_cover is None else max(0.0, min(1.0, 1.0 - cloud_cover / 100.0))

        return {
            "cloud_cover": cloud_cover,
            "humidity": humidity,
            "visibility_km": visibility_km,
            "wind_speed": wind_speed,
            "temperature": temperature,
            "dew_point": dew_point,
            "seeing_arcsec": None,
            "transparency": transparency,
        }
