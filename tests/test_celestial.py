from __future__ import annotations

from datetime import datetime, timezone

from astronomy import celestial

# Observer used by the bundled launchers.
LAT, LON = 43.2557, -79.8711

# Reference values pulled from JPL Horizons (OBSERVER ephemeris, geodetic site
# 280.128900,43.255700,0.100000, APPARENT='AIRLESS'). Refraction is switched off
# on both sides because Horizons holds it at a constant 0.6466 deg below the
# horizon, which is not a physical quantity to compare against.
HORIZONS_ANCHORS = [
    {
        "moment": datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc),
        "sun_az": 10.109912899,
        "sun_alt": -31.528378587,
        "moon_az": 2.485961656,
        "moon_alt": -34.957495089,
        "moon_illumination_percent": 0.40084,
    },
    {
        "moment": datetime(2026, 12, 14, 2, 0, tzinfo=timezone.utc),
        "sun_az": 280.743260032,
        "sun_alt": -45.536778380,
        "moon_az": 247.023945291,
        "moon_alt": -0.586156108,
        "moon_illumination_percent": 20.59760,
    },
]


def _angle_delta(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def test_julian_date_at_j2000_epoch() -> None:
    j2000 = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert abs(celestial.julian_date(j2000) - 2451545.0) < 1e-6


def test_naive_datetimes_are_treated_as_utc() -> None:
    naive = datetime(2026, 8, 13, 6, 0)
    aware = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)
    assert celestial.julian_date(naive) == celestial.julian_date(aware)


def test_sidereal_time_advances_faster_than_solar_time() -> None:
    start = datetime(2026, 8, 13, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 14, 0, 0, tzinfo=timezone.utc)
    drift = (celestial.gmst_deg(end) - celestial.gmst_deg(start)) % 360.0
    # A sidereal day is about four minutes short of a solar day.
    assert abs(drift - 0.9856) < 0.01


def test_sun_position_matches_horizons() -> None:
    for anchor in HORIZONS_ANCHORS:
        sun = celestial.sun_position(anchor["moment"])
        altitude, azimuth = celestial.equatorial_to_horizontal(
            sun.ra_deg,
            sun.dec_deg,
            LAT,
            LON,
            anchor["moment"],
            apply_refraction=False,
        )
        assert abs(altitude - anchor["sun_alt"]) < 0.01
        assert _angle_delta(azimuth, anchor["sun_az"]) < 0.01


def test_moon_position_matches_horizons_within_series_truncation() -> None:
    for anchor in HORIZONS_ANCHORS:
        sky = celestial.sky_context(LAT, LON, anchor["moment"])
        _, azimuth = celestial.equatorial_to_horizontal(
            sky.moon_ra_deg,
            sky.moon_dec_deg,
            LAT,
            LON,
            anchor["moment"],
            apply_refraction=False,
        )
        # Bounds are the worst case measured over 1249 samples spanning 2026;
        # see the astronomy.celestial module docstring.
        assert abs(sky.moon_altitude_deg - anchor["moon_alt"]) < 1.2
        assert _angle_delta(azimuth, anchor["moon_az"]) < 1.8
        assert (
            abs(
                sky.moon_illumination * 100.0
                - anchor["moon_illumination_percent"]
            )
            < 1.2
        )


def test_sky_context_reports_unrefracted_sun_altitude() -> None:
    # Twilight thresholds are defined on the geometric solar altitude, so the
    # value must not carry a refraction correction.
    moment = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)
    sky = celestial.sky_context(LAT, LON, moment)
    assert abs(sky.sun_altitude_deg - (-31.528378587)) < 0.01


def test_refraction_lifts_low_targets_and_vanishes_at_zenith() -> None:
    assert 0.4 < celestial.refraction_deg(0.0) < 0.7
    assert celestial.refraction_deg(45.0) < 0.02
    # Meaningless below the horizon, so it is not applied there.
    assert celestial.refraction_deg(-5.0) == 0.0


def test_circumpolar_target_never_sets_at_mid_northern_latitude() -> None:
    # Polaris-like declination: always up from 43 N.
    altitudes = [
        celestial.equatorial_to_horizontal(
            37.95, 89.26, LAT, LON, datetime(2026, 8, 13, hour, tzinfo=timezone.utc)
        )[0]
        for hour in range(24)
    ]
    assert min(altitudes) > 40.0


def test_longitude_of_date_is_zero_at_the_march_equinox() -> None:
    # The equinox is by definition the instant the Sun's longitude referred to
    # the equinox of date reaches 0, at 2026-03-20 ~14:46 UT.
    equinox = datetime(2026, 3, 20, 14, 46, tzinfo=timezone.utc)
    longitude = celestial.sun_position(equinox).ecliptic_longitude_deg
    assert min(longitude, 360.0 - longitude) < 0.05

    # The J2000 value lags it by the precession accumulated since 2000, so it
    # is not zero at that instant.
    j2000 = celestial.solar_longitude_j2000_deg(equinox)
    assert 0.3 < 360.0 - j2000 < 0.45


def test_solar_longitude_removes_precession_since_j2000() -> None:
    moment = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)
    of_date = celestial.sun_position(moment).ecliptic_longitude_deg
    j2000 = celestial.solar_longitude_j2000_deg(moment)
    # About 0.37 deg of general precession has accumulated by 2026.
    assert 0.3 < of_date - j2000 < 0.45


def test_angular_separation_handles_identical_and_opposite_points() -> None:
    assert celestial.angular_separation_deg(10.0, 20.0, 10.0, 20.0) < 1e-9
    assert abs(celestial.angular_separation_deg(0.0, 90.0, 0.0, -90.0) - 180.0) < 1e-9
    assert abs(celestial.angular_separation_deg(0.0, 0.0, 90.0, 0.0) - 90.0) < 1e-9


def test_topocentric_correction_lowers_the_moon_most_near_the_horizon() -> None:
    distance = 385000.0
    at_horizon = celestial.topocentric_altitude_deg(0.0, distance)
    at_zenith = celestial.topocentric_altitude_deg(90.0, distance)
    assert 0.9 < -at_horizon < 1.0
    assert abs(at_zenith - 90.0) < 1e-6


def test_solar_presence_code_matches_twilight_bands() -> None:
    assert celestial.solar_presence_code(5.0) == "*"
    assert celestial.solar_presence_code(-3.0) == "C"
    assert celestial.solar_presence_code(-9.0) == "N"
    assert celestial.solar_presence_code(-15.0) == "A"
    assert celestial.solar_presence_code(-25.0) == ""
