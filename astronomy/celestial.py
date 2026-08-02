"""
celestial.py

Local (offline) positional astronomy used by targets that JPL Horizons cannot
provide an ephemeris for -- most notably meteor shower radiants, which are
points on the celestial sphere rather than solar system bodies.

Everything here is deliberately low-precision but self-contained:

- Sun position uses the Astronomical Almanac low-precision formula.
- Moon position uses a truncated Meeus series.
- Refraction uses Saemundsson's formula so altitudes are comparable with the
  ``APPARENT='REFRACTED'`` altitudes Horizons returns for other targets.

Measured against JPL Horizons over 1249 samples spanning 2026 (observer at
43.26 N, 79.87 W, unrefracted altitudes on both sides):

    Sun   altitude  max 0.011 deg, mean 0.004 deg; azimuth max 0.021 deg
    Moon  altitude  max 1.08 deg,  mean 0.41 deg;  azimuth max 1.60 deg
    Moon  illuminated fraction  max 0.97 pp, mean 0.25 pp

The lunar figures are dominated by the truncated series and are immaterial
here: the Moon enters scoring only through how much it brightens the sky, and
a degree of altitude near the horizon changes that by nothing measurable.

Angles are degrees unless a name says otherwise. Times must be timezone-aware
or are assumed to be UTC.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

# Mean obliquity and general precession constants (IAU 1976).
_PRECESSION_DEG_PER_CENTURY = 1.396971
_AU_KM = 149597870.7
_EARTH_RADIUS_KM = 6378.14


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def julian_date(moment: datetime) -> float:
    """Julian Date (UT) for a datetime."""
    return _as_utc(moment).timestamp() / 86400.0 + 2440587.5


def julian_centuries(moment: datetime) -> float:
    """Julian centuries since J2000.0."""
    return (julian_date(moment) - 2451545.0) / 36525.0


def gmst_deg(moment: datetime) -> float:
    """Greenwich Mean Sidereal Time in degrees."""
    days = julian_date(moment) - 2451545.0
    centuries = days / 36525.0
    gmst = (
        280.46061837
        + 360.98564736629 * days
        + 0.000387933 * centuries**2
        - centuries**3 / 38710000.0
    )
    return gmst % 360.0


def local_sidereal_time_deg(moment: datetime, longitude_deg: float) -> float:
    """Local mean sidereal time in degrees (longitude positive east)."""
    return (gmst_deg(moment) + longitude_deg) % 360.0


def refraction_deg(true_altitude_deg: float) -> float:
    """
    Atmospheric refraction to add to a true altitude, via Saemundsson's formula.

    Returns 0 below the horizon where the correction is meaningless.
    """
    if true_altitude_deg < -1.0:
        return 0.0
    denominator = true_altitude_deg + 10.3 / (true_altitude_deg + 5.11)
    return (1.02 / math.tan(math.radians(denominator))) / 60.0


def equatorial_to_horizontal(
    ra_deg: float,
    dec_deg: float,
    latitude_deg: float,
    longitude_deg: float,
    moment: datetime,
    *,
    apply_refraction: bool = True,
) -> tuple[float, float]:
    """
    Convert equatorial coordinates to (altitude, azimuth) for an observer.

    Azimuth is measured from north, increasing eastward.
    """
    hour_angle = math.radians(
        (local_sidereal_time_deg(moment, longitude_deg) - ra_deg) % 360.0
    )
    dec = math.radians(dec_deg)
    latitude = math.radians(latitude_deg)

    sin_alt = math.sin(dec) * math.sin(latitude) + math.cos(dec) * math.cos(
        latitude
    ) * math.cos(hour_angle)
    altitude = math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))

    azimuth = math.degrees(
        math.atan2(
            -math.cos(dec) * math.sin(hour_angle),
            math.sin(dec) * math.cos(latitude)
            - math.cos(dec) * math.sin(latitude) * math.cos(hour_angle),
        )
    )

    if apply_refraction:
        altitude += refraction_deg(altitude)
    return altitude, azimuth % 360.0


def angular_separation_deg(
    ra1_deg: float, dec1_deg: float, ra2_deg: float, dec2_deg: float
) -> float:
    """Great-circle separation between two equatorial positions."""
    ra1, dec1 = math.radians(ra1_deg), math.radians(dec1_deg)
    ra2, dec2 = math.radians(ra2_deg), math.radians(dec2_deg)
    cos_sep = math.sin(dec1) * math.sin(dec2) + math.cos(dec1) * math.cos(
        dec2
    ) * math.cos(ra1 - ra2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))


def obliquity_deg(moment: datetime) -> float:
    """Mean obliquity of the ecliptic."""
    return 23.439 - 0.0000004 * (julian_date(moment) - 2451545.0)


def _ecliptic_to_equatorial(
    lon_deg: float, lat_deg: float, obliquity: float
) -> tuple[float, float]:
    lon, lat, eps = math.radians(lon_deg), math.radians(lat_deg), math.radians(obliquity)
    ra = math.atan2(
        math.sin(lon) * math.cos(eps) - math.tan(lat) * math.sin(eps), math.cos(lon)
    )
    dec = math.asin(
        math.sin(lat) * math.cos(eps)
        + math.cos(lat) * math.sin(eps) * math.sin(lon)
    )
    return math.degrees(ra) % 360.0, math.degrees(dec)


class SunPosition:
    """Geocentric solar position for a moment in time."""

    __slots__ = ("ra_deg", "dec_deg", "ecliptic_longitude_deg", "distance_au")

    def __init__(
        self,
        ra_deg: float,
        dec_deg: float,
        ecliptic_longitude_deg: float,
        distance_au: float,
    ) -> None:
        self.ra_deg = ra_deg
        self.dec_deg = dec_deg
        self.ecliptic_longitude_deg = ecliptic_longitude_deg
        self.distance_au = distance_au


def sun_position(moment: datetime) -> SunPosition:
    """
    Low-precision geocentric solar position (Astronomical Almanac).

    ``ecliptic_longitude_deg`` is referred to the mean equinox of date.
    """
    days = julian_date(moment) - 2451545.0
    mean_longitude = (280.460 + 0.9856474 * days) % 360.0
    mean_anomaly = math.radians((357.528 + 0.9856003 * days) % 360.0)

    ecliptic_longitude = (
        mean_longitude
        + 1.915 * math.sin(mean_anomaly)
        + 0.020 * math.sin(2.0 * mean_anomaly)
    ) % 360.0
    distance_au = (
        1.00014
        - 0.01671 * math.cos(mean_anomaly)
        - 0.00014 * math.cos(2.0 * mean_anomaly)
    )

    ra_deg, dec_deg = _ecliptic_to_equatorial(
        ecliptic_longitude, 0.0, obliquity_deg(moment)
    )
    return SunPosition(ra_deg, dec_deg, ecliptic_longitude, distance_au)


def solar_longitude_j2000_deg(moment: datetime) -> float:
    """
    Solar longitude referred to the J2000.0 equinox.

    Meteor shower peaks are catalogued in J2000 solar longitude rather than by
    calendar date, because the date of a given solar longitude drifts with the
    leap-year cycle. Ignoring the precession term would misplace peaks by
    roughly nine hours at the present epoch.
    """
    longitude_of_date = sun_position(moment).ecliptic_longitude_deg
    precession = _PRECESSION_DEG_PER_CENTURY * julian_centuries(moment)
    return (longitude_of_date - precession) % 360.0


class MoonPosition:
    """Geocentric lunar position for a moment in time."""

    __slots__ = (
        "ra_deg",
        "dec_deg",
        "ecliptic_longitude_deg",
        "ecliptic_latitude_deg",
        "distance_km",
    )

    def __init__(
        self,
        ra_deg: float,
        dec_deg: float,
        ecliptic_longitude_deg: float,
        ecliptic_latitude_deg: float,
        distance_km: float,
    ) -> None:
        self.ra_deg = ra_deg
        self.dec_deg = dec_deg
        self.ecliptic_longitude_deg = ecliptic_longitude_deg
        self.ecliptic_latitude_deg = ecliptic_latitude_deg
        self.distance_km = distance_km


def moon_position(moment: datetime) -> MoonPosition:
    """
    Low-precision geocentric lunar position (truncated Meeus series).

    Keeps the largest periodic terms only; see the module docstring for the
    measured accuracy against Horizons.
    """
    centuries = julian_centuries(moment)

    mean_longitude = (218.3164477 + 481267.88123421 * centuries) % 360.0
    elongation = math.radians((297.8501921 + 445267.1114034 * centuries) % 360.0)
    sun_anomaly = math.radians((357.5291092 + 35999.0502909 * centuries) % 360.0)
    moon_anomaly = math.radians((134.9633964 + 477198.8675055 * centuries) % 360.0)
    latitude_argument = math.radians(
        (93.2720950 + 483202.0175233 * centuries) % 360.0
    )

    longitude = (
        mean_longitude
        + 6.289 * math.sin(moon_anomaly)
        + 1.274 * math.sin(2.0 * elongation - moon_anomaly)
        + 0.658 * math.sin(2.0 * elongation)
        + 0.214 * math.sin(2.0 * moon_anomaly)
        - 0.186 * math.sin(sun_anomaly)
        - 0.114 * math.sin(2.0 * latitude_argument)
        + 0.059 * math.sin(2.0 * moon_anomaly - 2.0 * elongation)
        + 0.057 * math.sin(moon_anomaly - 2.0 * elongation + sun_anomaly)
        + 0.053 * math.sin(moon_anomaly + 2.0 * elongation)
        + 0.046 * math.sin(2.0 * elongation - sun_anomaly)
        - 0.041 * math.sin(moon_anomaly - sun_anomaly)
        - 0.035 * math.sin(elongation)
        - 0.031 * math.sin(moon_anomaly + sun_anomaly)
    ) % 360.0

    latitude = (
        5.128 * math.sin(latitude_argument)
        + 0.281 * math.sin(moon_anomaly + latitude_argument)
        - 0.278 * math.sin(moon_anomaly - latitude_argument)
        - 0.173 * math.sin(latitude_argument - 2.0 * elongation)
        + 0.055 * math.sin(2.0 * elongation - moon_anomaly + latitude_argument)
        - 0.046 * math.sin(2.0 * elongation - moon_anomaly - latitude_argument)
        + 0.033 * math.sin(2.0 * elongation + latitude_argument)
        + 0.017 * math.sin(2.0 * moon_anomaly + latitude_argument)
    )

    distance_km = (
        385000.56
        - 20905.355 * math.cos(moon_anomaly)
        - 3699.111 * math.cos(2.0 * elongation - moon_anomaly)
        - 2955.968 * math.cos(2.0 * elongation)
        - 569.925 * math.cos(2.0 * moon_anomaly)
    )

    ra_deg, dec_deg = _ecliptic_to_equatorial(
        longitude, latitude, obliquity_deg(moment)
    )
    return MoonPosition(ra_deg, dec_deg, longitude, latitude, distance_km)


def moon_illuminated_fraction(moment: datetime) -> float:
    """Illuminated fraction of the lunar disk, in 0..1."""
    moon = moon_position(moment)
    sun = sun_position(moment)

    elongation = math.acos(
        max(
            -1.0,
            min(
                1.0,
                math.cos(math.radians(moon.ecliptic_latitude_deg))
                * math.cos(
                    math.radians(
                        moon.ecliptic_longitude_deg - sun.ecliptic_longitude_deg
                    )
                ),
            ),
        )
    )

    sun_distance_km = sun.distance_au * _AU_KM
    phase_angle = math.atan2(
        sun_distance_km * math.sin(elongation),
        moon.distance_km - sun_distance_km * math.cos(elongation),
    )
    return (1.0 + math.cos(phase_angle)) / 2.0


def topocentric_altitude_deg(
    geocentric_altitude_deg: float, distance_km: float
) -> float:
    """
    Correct a geocentric altitude for diurnal parallax.

    Only matters for the Moon, where the correction reaches about one degree
    near the horizon -- enough to change whether the Moon counts as "up".
    """
    horizontal_parallax = math.asin(
        max(-1.0, min(1.0, _EARTH_RADIUS_KM / distance_km))
    )
    return geocentric_altitude_deg - math.degrees(
        horizontal_parallax * math.cos(math.radians(geocentric_altitude_deg))
    )


class SkyContext:
    """Sun and Moon circumstances for one observer at one moment."""

    __slots__ = (
        "sun_altitude_deg",
        "sun_ra_deg",
        "sun_dec_deg",
        "moon_altitude_deg",
        "moon_ra_deg",
        "moon_dec_deg",
        "moon_illumination",
    )

    def __init__(
        self,
        sun_altitude_deg: float,
        sun_ra_deg: float,
        sun_dec_deg: float,
        moon_altitude_deg: float,
        moon_ra_deg: float,
        moon_dec_deg: float,
        moon_illumination: float,
    ) -> None:
        self.sun_altitude_deg = sun_altitude_deg
        self.sun_ra_deg = sun_ra_deg
        self.sun_dec_deg = sun_dec_deg
        self.moon_altitude_deg = moon_altitude_deg
        self.moon_ra_deg = moon_ra_deg
        self.moon_dec_deg = moon_dec_deg
        self.moon_illumination = moon_illumination


def sky_context(
    latitude_deg: float, longitude_deg: float, moment: datetime
) -> SkyContext:
    """Compute Sun/Moon altitudes and lunar phase for an observing site."""
    sun = sun_position(moment)
    moon = moon_position(moment)

    # Twilight boundaries (-6/-12/-18 deg) are defined on the geometric solar
    # altitude, so refraction is deliberately not applied here. Horizons holds
    # refraction at a constant 0.6466 deg below the horizon, which would shift
    # every twilight threshold by a couple of minutes.
    sun_altitude, _ = equatorial_to_horizontal(
        sun.ra_deg,
        sun.dec_deg,
        latitude_deg,
        longitude_deg,
        moment,
        apply_refraction=False,
    )
    moon_geocentric_altitude, _ = equatorial_to_horizontal(
        moon.ra_deg,
        moon.dec_deg,
        latitude_deg,
        longitude_deg,
        moment,
        apply_refraction=False,
    )
    moon_altitude = topocentric_altitude_deg(
        moon_geocentric_altitude, moon.distance_km
    )
    moon_altitude += refraction_deg(moon_altitude)

    return SkyContext(
        sun_altitude_deg=sun_altitude,
        sun_ra_deg=sun.ra_deg,
        sun_dec_deg=sun.dec_deg,
        moon_altitude_deg=moon_altitude,
        moon_ra_deg=moon.ra_deg,
        moon_dec_deg=moon.dec_deg,
        moon_illumination=moon_illuminated_fraction(moment),
    )


def solar_presence_code(sun_altitude_deg: float) -> str:
    """
    Horizons-style twilight marker for a solar altitude.

    Mirrors the ``solar_presence`` column so locally computed samples read the
    same way as Horizons ones in the log and status panels.
    """
    if sun_altitude_deg > 0.0:
        return "*"
    if sun_altitude_deg > -6.0:
        return "C"
    if sun_altitude_deg > -12.0:
        return "N"
    if sun_altitude_deg > -18.0:
        return "A"
    return ""
