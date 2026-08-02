from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from astronomy.meteor_showers import get_shower
from astronomy.observation_scorer import ObservationContext
from astronomy.scorer_factory import create_scorer, get_registered_target_types
from astronomy.scorers import MeteorShowerScorer

PERSEIDS = get_shower("PER")
PEAK = PERSEIDS.next_peak(datetime(2026, 8, 1, tzinfo=timezone.utc))


def _context(**overrides) -> ObservationContext:
    defaults = dict(
        target_alt=50.0,
        sun_alt=-30.0,
        solar_elongation=120.0,
        moon_alt=-40.0,
        moon_illumination=0.0,
        moon_separation=120.0,
        cloud_cover=0.0,
        humidity=60.0,
        visibility_km=20.0,
        wind_speed=8.0,
        temperature=18.0,
        dew_point=10.0,
        target_name="Perseids",
        observation_time=PEAK,
    )
    defaults.update(overrides)
    return ObservationContext(**defaults)


@pytest.fixture
def scorer() -> MeteorShowerScorer:
    return MeteorShowerScorer(PERSEIDS)


def test_factory_registers_a_type_per_shower() -> None:
    types = get_registered_target_types()
    assert "meteor_shower" in types
    assert "meteor_shower_per" in types
    assert "meteor_shower_gem" in types

    bound = create_scorer("meteor_shower_per")
    assert isinstance(bound, MeteorShowerScorer)
    assert bound.shower is PERSEIDS
    # Each shower type must bind its own shower, not the last one registered.
    assert create_scorer("meteor_shower_gem").shower is get_shower("GEM")


def test_generic_type_resolves_the_shower_from_the_target_name() -> None:
    generic = create_scorer("meteor_shower")
    assert isinstance(generic, MeteorShowerScorer)
    assert generic.shower is None
    assert generic.resolve_shower(_context()) is PERSEIDS
    assert generic.resolve_shower(_context(target_name="Mars")) is None


def test_daylight_and_a_set_radiant_are_hard_gates(scorer) -> None:
    assert not scorer.evaluate(_context(sun_alt=2.0)).observable
    assert scorer.evaluate(_context(sun_alt=2.0)).score == 0
    assert not scorer.evaluate(_context(target_alt=-5.0)).observable
    assert (
        scorer.evaluate(_context(target_alt=-5.0)).limiting_factor
        == "Radiant below horizon"
    )
    # Nautical twilight is dark enough to start counting.
    assert scorer.evaluate(_context(sun_alt=-8.0)).observable


def test_score_rises_with_radiant_altitude(scorer) -> None:
    scores = [scorer.evaluate(_context(target_alt=alt)).score for alt in (5, 20, 45, 75)]
    assert scores == sorted(scores)
    assert scores[-1] > scores[0]


def test_altitude_subscore_is_the_sine_of_the_radiant_altitude(scorer) -> None:
    subscores = scorer.compute_subscores(_context(target_alt=30.0))
    assert subscores["alt"] == pytest.approx(0.5, abs=1e-6)


def test_moonlight_penalty_ignores_separation_from_the_radiant(scorer) -> None:
    # Meteors appear all over the sky, so where the Moon sits relative to the
    # radiant must not change the score.
    near = scorer.evaluate(
        _context(moon_alt=50.0, moon_illumination=1.0, moon_separation=5.0)
    )
    far = scorer.evaluate(
        _context(moon_alt=50.0, moon_illumination=1.0, moon_separation=175.0)
    )
    assert near.score == far.score

    # But a bright Moon that is up must cost, and one below the horizon must not.
    full_moon_up = scorer.evaluate(_context(moon_alt=50.0, moon_illumination=1.0))
    moon_down = scorer.evaluate(_context(moon_alt=-10.0, moon_illumination=1.0))
    assert full_moon_up.score < moon_down.score
    assert scorer.score_moon(_context(moon_alt=-10.0, moon_illumination=1.0)) == 1.0


def test_solar_elongation_is_not_scored(scorer) -> None:
    subscores = scorer.compute_subscores(_context())
    assert "elong" not in subscores
    assert scorer.evaluate(_context(solar_elongation=5.0)).score == scorer.evaluate(
        _context(solar_elongation=170.0)
    ).score


def test_date_matters_independently_of_geometry(scorer) -> None:
    # Same sky, three weeks earlier: the stream is simply not flowing yet.
    at_peak = scorer.evaluate(_context(observation_time=PEAK))
    off_peak = scorer.evaluate(_context(observation_time=PEAK - timedelta(days=21)))
    assert at_peak.score > off_peak.score
    assert off_peak.limiting_factor == "distance from the shower peak"


def test_estimated_rate_is_reported_and_tracks_conditions(scorer) -> None:
    result = scorer.evaluate(_context())
    assert result.custom_scores["ZHR"] == pytest.approx(PERSEIDS.peak_zhr, rel=0.05)
    assert result.custom_scores["meteors/hr"] > 0.0
    assert result.custom_scores["limiting mag"] == pytest.approx(6.0)

    # A bright Moon raises sky brightness, which cuts the countable rate.
    moonlit = scorer.evaluate(_context(moon_alt=60.0, moon_illumination=1.0))
    assert moonlit.custom_scores["limiting mag"] < 4.0
    assert moonlit.custom_scores["meteors/hr"] < result.custom_scores["meteors/hr"]

    # Cloud blocks a proportional share of the sky.
    clouded = scorer.evaluate(_context(cloud_cover=50.0))
    assert clouded.custom_scores["meteors/hr"] == pytest.approx(
        result.custom_scores["meteors/hr"] * 0.5, rel=0.02
    )


def test_rate_is_omitted_when_the_shower_or_date_is_unknown() -> None:
    generic = MeteorShowerScorer()
    assert generic.evaluate(_context(target_name="Mars")).custom_scores == {}
    assert generic.evaluate(_context(observation_time=None)).custom_scores == {}


def test_reasons_explain_the_headline_limits(scorer) -> None:
    at_peak = " ".join(scorer.evaluate(_context()).reasons)
    assert "peak" in at_peak

    low = " ".join(scorer.evaluate(_context(target_alt=8.0)).reasons)
    assert "earthgrazer" in low

    moonlit = " ".join(
        scorer.evaluate(_context(moon_alt=60.0, moon_illumination=0.9)).reasons
    )
    assert "Moon is up" in moonlit

    twilight = " ".join(scorer.evaluate(_context(sun_alt=-10.0)).reasons)
    assert "astronomically dark" in twilight
