from __future__ import annotations

from datetime import datetime, timezone

import pytest

from astronomy.meteor_showers import (
    SHOWERS,
    UnknownShowerError,
    get_shower,
    observed_hourly_rate,
    parse_target_command,
    shower_target_command,
)

PERSEIDS = get_shower("PER")


def test_every_shower_has_a_unique_code_and_a_positive_peak_rate() -> None:
    codes = [shower.code for shower in SHOWERS]
    assert len(codes) == len(set(codes))
    for shower in SHOWERS:
        assert shower.peak_zhr > 0.0
        assert 0.0 <= shower.peak_solar_longitude_deg < 360.0
        assert -90.0 <= shower.radiant_dec_deg <= 90.0
        assert shower.population_index > 1.0


@pytest.mark.parametrize(
    "code,expected_date",
    [
        ("PER", "2026-08-13"),
        ("ORI", "2026-10-21"),
        ("LEO", "2026-11-17"),
        ("GEM", "2026-12-14"),
        ("URS", "2026-12-22"),
        # Falls in the following January, so it exercises the year rollover.
        ("QUA", "2027-01-04"),
    ],
)
def test_next_peak_lands_on_the_published_date(code: str, expected_date: str) -> None:
    reference = datetime(2026, 8, 2, tzinfo=timezone.utc)
    peak = get_shower(code).next_peak(reference)
    assert peak.strftime("%Y-%m-%d") == expected_date
    assert peak >= reference


def test_next_peak_is_a_fixed_point_of_the_solar_longitude() -> None:
    peak = PERSEIDS.next_peak(datetime(2026, 8, 2, tzinfo=timezone.utc))
    assert abs(PERSEIDS.solar_longitude_offset_deg(peak)) < 1e-4


def test_zhr_peaks_at_the_maximum_and_falls_away_either_side() -> None:
    peak = PERSEIDS.next_peak(datetime(2026, 8, 2, tzinfo=timezone.utc))
    at_peak = PERSEIDS.zhr_at(peak)
    assert at_peak == pytest.approx(PERSEIDS.peak_zhr, rel=0.02)

    for offset_days in (1, 3, 7):
        before = PERSEIDS.zhr_at(peak.replace() - _days(offset_days))
        after = PERSEIDS.zhr_at(peak + _days(offset_days))
        assert before < at_peak
        assert after < at_peak
        # The Perseids decline faster after maximum than they build before it.
        assert after < before


def test_zhr_is_zero_outside_the_activity_window() -> None:
    peak = PERSEIDS.next_peak(datetime(2026, 8, 2, tzinfo=timezone.utc))
    assert PERSEIDS.zhr_at(peak + _days(40)) == 0.0
    assert PERSEIDS.zhr_at(peak - _days(60)) == 0.0
    assert not PERSEIDS.is_active(peak + _days(40))
    assert PERSEIDS.is_active(peak)


def test_radiant_drifts_eastward_across_the_activity_period() -> None:
    peak = PERSEIDS.next_peak(datetime(2026, 8, 2, tzinfo=timezone.utc))
    ra_at_peak, dec_at_peak = PERSEIDS.radiant_at(peak)
    assert ra_at_peak == pytest.approx(PERSEIDS.radiant_ra_deg, abs=0.1)
    assert dec_at_peak == pytest.approx(PERSEIDS.radiant_dec_deg, abs=0.1)

    ra_later, _ = PERSEIDS.radiant_at(peak + _days(10))
    ra_earlier, _ = PERSEIDS.radiant_at(peak - _days(10))
    assert ra_later > ra_at_peak > ra_earlier
    assert ra_later - ra_earlier == pytest.approx(
        20.0 * PERSEIDS.drift_ra_deg_per_day, rel=0.05
    )


def test_days_from_peak_is_signed() -> None:
    peak = PERSEIDS.next_peak(datetime(2026, 8, 2, tzinfo=timezone.utc))
    assert PERSEIDS.days_from_peak(peak - _days(3)) == pytest.approx(-3.0, abs=0.05)
    assert PERSEIDS.days_from_peak(peak + _days(3)) == pytest.approx(3.0, abs=0.05)


def test_target_commands_round_trip() -> None:
    assert shower_target_command(PERSEIDS) == "SHOWER=PER"
    assert parse_target_command("SHOWER=PER") is PERSEIDS
    assert parse_target_command("'SHOWER=PER'") is PERSEIDS
    assert parse_target_command("shower=per") is PERSEIDS
    assert parse_target_command("PER") is PERSEIDS
    assert parse_target_command("Perseids") is PERSEIDS


def test_unknown_targets_are_rejected() -> None:
    with pytest.raises(UnknownShowerError):
        parse_target_command("SHOWER=NOPE")
    with pytest.raises(UnknownShowerError):
        # A Horizons body command is not a shower.
        parse_target_command("'499'")
    with pytest.raises(UnknownShowerError):
        get_shower("Leonid")


def test_observed_rate_follows_the_standard_zhr_relation() -> None:
    # At the zenith under a 6.5 mag sky with clear view, the observed rate is
    # the ZHR by definition.
    assert observed_hourly_rate(100.0, 90.0, 6.5, 2.2) == pytest.approx(100.0)
    # Halved when the radiant sits at 30 degrees, since sin(30) = 0.5.
    assert observed_hourly_rate(100.0, 30.0, 6.5, 2.2) == pytest.approx(50.0)
    # A brighter sky costs r per magnitude.
    assert observed_hourly_rate(100.0, 90.0, 5.5, 2.2) == pytest.approx(100.0 / 2.2)
    # Obstructed sky scales linearly.
    assert observed_hourly_rate(
        100.0, 90.0, 6.5, 2.2, obstructed_sky_fraction=0.25
    ) == pytest.approx(75.0)
    # Nothing is seen with the radiant down.
    assert observed_hourly_rate(100.0, -1.0, 6.5, 2.2) == 0.0


def _days(count: float):
    from datetime import timedelta

    return timedelta(days=count)
