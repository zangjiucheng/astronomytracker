from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime


class HorizonsError(RuntimeError):
    pass


def ra_to_hms(ra_deg: float) -> str:
    hours = ra_deg / 15.0
    h = int(hours)
    m = int((hours - h) * 60)
    s = ((hours - h) * 60 - m) * 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def dec_to_dms(dec_deg: float) -> str:
    sign = "+" if dec_deg >= 0 else "-"
    dec_deg = abs(dec_deg)
    d = int(dec_deg)
    m = int((dec_deg - d) * 60)
    s = ((dec_deg - d) * 60 - m) * 60
    return f"{sign}{d:02d}:{m:02d}:{s:04.1f}"


class HorizonsParseError(HorizonsError):
    pass


@dataclass
class ObserverLocation:
    latitude_deg: float
    longitude_deg: float
    elevation_km: float


@dataclass
class EphemerisSample:
    utc_time: datetime
    local_time: datetime
    ra_deg: float
    dec_deg: float
    az_deg: float
    el_deg: float
    solar_elong_deg: float
    compass_direction: str
    visibility_status: str
    range_au: float
    range_rate_kms: float
    solar_presence: str
    interferer_presence: str
    solar_alignment_code: str


@dataclass
class TrackerState:
    target_command: str = ""
    location: ObserverLocation = field(
        default_factory=lambda: ObserverLocation(43.2557, -79.8711, 0.10)
    )
    refresh_interval_sec: int = 10
    is_tracking: bool = False
    latest_sample: EphemerisSample | None = None
    history: list[EphemerisSample] = field(default_factory=list)
    last_error: str = ""


def compass_from_azimuth(az_deg: float) -> str:
    directions = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    index = round(az_deg / 22.5) % 16
    return directions[index]


def format_local_time(utc_time: datetime) -> str:
    return utc_time.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
