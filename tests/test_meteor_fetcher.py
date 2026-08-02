from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from astronomy.meteor_fetcher import MeteorRadiantFetcher
from astronomy.meteor_showers import UnknownShowerError, get_shower
from astronomy.tracker_state import ObserverLocation

LOCATION = ObserverLocation(43.2557, -79.8711, 0.10)
PERSEIDS = get_shower("PER")

# Late on the night of the 2026 maximum: radiant well up, Sun deep below the
# horizon, Moon down (new moon falls on the peak that year).
PEAK_NIGHT = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
def fetcher() -> MeteorRadiantFetcher:
    return MeteorRadiantFetcher()


def test_sample_places_the_radiant_in_perseus(fetcher) -> None:
    sample = fetcher.fetch_current_ephemeris("SHOWER=PER", LOCATION, PEAK_NIGHT)
    radiant_ra, radiant_dec = PERSEIDS.radiant_at(PEAK_NIGHT)
    assert sample.ra_deg == pytest.approx(radiant_ra)
    assert sample.dec_deg == pytest.approx(radiant_dec)
    # 06:00 UT is 02:00 local, with Perseus well up in the northeast and still
    # climbing towards dawn.
    assert sample.el_deg > 40.0
    assert 0.0 <= sample.az_deg < 90.0
    assert sample.compass_direction in {"N", "NNE", "NE", "ENE"}
    assert sample.visibility_status == "Radiant above horizon"


def test_sample_carries_real_sky_context(fetcher) -> None:
    sample = fetcher.fetch_current_ephemeris("SHOWER=PER", LOCATION, PEAK_NIGHT)
    # Astronomical darkness, and a new moon below the horizon.
    assert sample.sun_alt_deg is not None and sample.sun_alt_deg < -18.0
    assert sample.solar_presence == ""
    assert sample.moon_alt_deg is not None and sample.moon_alt_deg < 0.0
    assert sample.interferer_presence == ""
    assert sample.moon_illumination is not None
    assert sample.moon_illumination < 0.02
    assert sample.moon_separation_deg is not None
    assert 0.0 <= sample.moon_separation_deg <= 180.0
    assert 0.0 <= sample.solar_elong_deg <= 180.0


def test_sample_reports_stream_velocity_as_an_approach_rate(fetcher) -> None:
    sample = fetcher.fetch_current_ephemeris("SHOWER=PER", LOCATION, PEAK_NIGHT)
    assert sample.range_rate_kms == -PERSEIDS.velocity_kms
    assert sample.range_au > 0.0


def test_radiant_sets_below_the_horizon_for_a_southern_observer(fetcher) -> None:
    # The Perseid radiant at +58 declination never rises from deep southern
    # latitudes, which is why the shower is a northern one.
    southern = ObserverLocation(-45.0, 170.0, 0.0)
    for hour in range(24):
        sample = fetcher.fetch_current_ephemeris(
            "SHOWER=PER", southern, PEAK_NIGHT + timedelta(hours=hour)
        )
        assert sample.el_deg < 0.0
        assert sample.visibility_status == "Radiant below horizon"


def test_current_ephemeris_defaults_to_now(fetcher) -> None:
    before = datetime.now(timezone.utc)
    sample = fetcher.fetch_current_ephemeris("SHOWER=PER", LOCATION)
    after = datetime.now(timezone.utc)
    assert before <= sample.utc_time <= after


def test_range_covers_the_window_at_the_requested_step(fetcher) -> None:
    start = datetime(2026, 8, 13, 0, 0, tzinfo=timezone.utc)
    stop = start + timedelta(hours=6)
    samples = fetcher.fetch_ephemeris_range("SHOWER=PER", LOCATION, start, stop, 5)

    assert len(samples) == 73  # inclusive of both endpoints
    assert samples[0].utc_time == start
    assert samples[-1].utc_time == stop
    gaps = {
        (b.utc_time - a.utc_time).total_seconds()
        for a, b in zip(samples, samples[1:])
    }
    assert gaps == {300.0}
    # The radiant climbs steadily through the second half of the night.
    assert samples[-1].el_deg > samples[0].el_deg


def test_naive_times_are_treated_as_utc(fetcher) -> None:
    naive = fetcher.fetch_current_ephemeris(
        "SHOWER=PER", LOCATION, datetime(2026, 8, 13, 6, 0)
    )
    aware = fetcher.fetch_current_ephemeris("SHOWER=PER", LOCATION, PEAK_NIGHT)
    assert naive.el_deg == pytest.approx(aware.el_deg)
    assert naive.utc_time.tzinfo is not None


def test_unknown_shower_command_is_rejected(fetcher) -> None:
    with pytest.raises(UnknownShowerError):
        fetcher.fetch_current_ephemeris("'499'", LOCATION, PEAK_NIGHT)


def test_fetcher_makes_no_network_calls_for_ephemerides(monkeypatch, fetcher) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("radiant ephemerides must be computed locally")

    monkeypatch.setattr("requests.Session.get", explode)
    fetcher.fetch_current_ephemeris("SHOWER=PER", LOCATION, PEAK_NIGHT)
    fetcher.fetch_ephemeris_range(
        "SHOWER=PER", LOCATION, PEAK_NIGHT, PEAK_NIGHT + timedelta(hours=1), 10
    )
