from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from astronomy.observation_scorer import ObservationContext
from astronomy.scorers import (
    BaseFallbackScorer,
    DeepSkyScorer,
    MoonScorer,
    NearSolarCometScorer,
    PlanetScorer,
)
from astronomy.scorer_factory import (
    create_scorer,
    get_registered_target_types,
    register_scorer,
)


def test_base_fallback_subscores_do_not_include_env() -> None:
    scorer = BaseFallbackScorer()
    ctx = ObservationContext(target_alt=35.0, sun_alt=-14.0, solar_elongation=50.0)

    subscores = scorer.compute_subscores(ctx)
    assert "env" not in subscores


def test_deep_sky_subscores_include_env() -> None:
    scorer = DeepSkyScorer()
    ctx = ObservationContext(
        target_alt=35.0, sun_alt=-14.0, solar_elongation=50.0, bortle=8.0
    )

    subscores = scorer.compute_subscores(ctx)
    assert "env" in subscores


def test_moon_scorer_ignores_moonlight_penalty() -> None:
    scorer = MoonScorer()
    harsh_moon_ctx = ObservationContext(
        target_alt=45.0,
        sun_alt=-8.0,
        solar_elongation=80.0,
        moon_alt=60.0,
        moon_illumination=1.0,
        moon_separation=5.0,
    )

    assert scorer.score_moon(harsh_moon_ctx) == 1.0


def test_near_solar_comet_scorer_hard_gates() -> None:
    scorer = NearSolarCometScorer()
    ctx_below = ObservationContext(
        target_alt=-5.0, sun_alt=-10.0, solar_elongation=20.0
    )
    ctx_sun_up = ObservationContext(target_alt=30.0, sun_alt=5.0, solar_elongation=20.0)
    ctx_close = ObservationContext(target_alt=30.0, sun_alt=-10.0, solar_elongation=5.0)
    ctx_good = ObservationContext(target_alt=30.0, sun_alt=-10.0, solar_elongation=20.0)

    assert scorer.check_hard_gates(ctx_below) == "Target below horizon"
    assert scorer.check_hard_gates(ctx_sun_up) == "Sun above horizon"
    assert scorer.check_hard_gates(ctx_close) == "Target too close to the Sun"
    assert scorer.check_hard_gates(ctx_good) is None


def test_planet_scorer_hard_gates() -> None:
    scorer = PlanetScorer()
    ctx_below = ObservationContext(
        target_alt=-5.0, sun_alt=-10.0, solar_elongation=30.0
    )
    ctx_daylight = ObservationContext(
        target_alt=30.0, sun_alt=10.0, solar_elongation=30.0
    )
    ctx_good = ObservationContext(target_alt=30.0, sun_alt=-5.0, solar_elongation=30.0)

    assert scorer.check_hard_gates(ctx_below) == "Target below horizon"
    assert (
        scorer.check_hard_gates(ctx_daylight)
        == "Daylight too strong for practical observation"
    )
    assert scorer.check_hard_gates(ctx_good) is None


def test_deep_sky_scorer_environment() -> None:
    scorer = DeepSkyScorer()
    ctx_clear_dark = ObservationContext(
        target_alt=45.0,
        sun_alt=-18.0,
        solar_elongation=50.0,
        cloud_cover=0.0,
        bortle=2.0,
    )
    ctx_cloudy_light_pollution = ObservationContext(
        target_alt=45.0,
        sun_alt=-18.0,
        solar_elongation=50.0,
        cloud_cover=80.0,
        bortle=9.0,
    )

    env_clear = scorer.score_environment(ctx_clear_dark)
    env_cloudy = scorer.score_environment(ctx_cloudy_light_pollution)
    assert env_clear > env_cloudy
    assert 0.0 <= env_clear <= 1.0
    assert 0.0 <= env_cloudy <= 1.0


def test_scorer_evaluate_returns_result_with_expected_fields() -> None:
    scorer = BaseFallbackScorer()
    ctx = ObservationContext(target_alt=45.0, sun_alt=-15.0, solar_elongation=50.0)

    result = scorer.evaluate(ctx)

    assert hasattr(result, "score")
    assert hasattr(result, "status")
    assert hasattr(result, "observable")
    assert hasattr(result, "reasons")
    assert hasattr(result, "subscores")
    assert hasattr(result, "custom_scores")
    assert 0 <= result.score <= 100


def test_scorer_evaluate_blocks_below_horizon() -> None:
    scorer = BaseFallbackScorer()
    ctx = ObservationContext(target_alt=-10.0, sun_alt=-15.0, solar_elongation=50.0)

    result = scorer.evaluate(ctx)

    assert result.score == 0
    assert result.observable is False
    assert result.status == "Not observable"
    assert "Target below horizon" in result.reasons


def test_scorer_weights_sum_to_one() -> None:
    for scorer_class in [
        BaseFallbackScorer,
        DeepSkyScorer,
        MoonScorer,
        PlanetScorer,
        NearSolarCometScorer,
    ]:
        scorer = scorer_class()
        total_weight = sum(scorer.SCORE_WEIGHTS.values())
        assert abs(total_weight - 1.0) < 0.001, (
            f"{scorer_class.__name__} weights sum to {total_weight}"
        )


def test_factory_creates_correct_scorer_types() -> None:
    registered_types = get_registered_target_types()
    assert "deep_sky" in registered_types
    assert "moon" in registered_types
    assert "planet" in registered_types
    assert "near_solar_comet" in registered_types


def test_factory_falls_back_to_base_for_unknown_type() -> None:
    scorer = create_scorer("unknown_type_xyz")
    assert isinstance(scorer, BaseFallbackScorer)


def test_factory_case_insensitive() -> None:
    scorer_lower = create_scorer("moon")
    scorer_upper = create_scorer("MOON")
    scorer_mixed = create_scorer("Moon")

    assert type(scorer_lower) == MoonScorer
    assert type(scorer_upper) == MoonScorer
    assert type(scorer_mixed) == MoonScorer


def test_register_custom_scorer() -> None:
    register_scorer("test_custom", MoonScorer)
    scorer = create_scorer("test_custom")
    assert isinstance(scorer, MoonScorer)


def test_register_scorer_rejects_empty_type() -> None:
    try:
        register_scorer("   ", MoonScorer)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_build_reasons_adds_environment_warning() -> None:
    scorer = DeepSkyScorer()
    ctx = ObservationContext(
        target_alt=45.0,
        sun_alt=-18.0,
        solar_elongation=50.0,
        cloud_cover=80.0,
        bortle=9.0,
    )

    subscores = scorer.compute_subscores(ctx)
    reasons = scorer.build_reasons(ctx, subscores)

    assert any("Cloud cover or light pollution" in r for r in reasons)


def test_score_to_status_boundaries() -> None:
    scorer = BaseFallbackScorer()

    assert scorer.score_to_status(0) == "Not observable"
    assert scorer.score_to_status(15) == "Not observable"
    assert scorer.score_to_status(16) == "Very poor"
    assert scorer.score_to_status(35) == "Very poor"
    assert scorer.score_to_status(36) == "Poor"
    assert scorer.score_to_status(55) == "Poor"
    assert scorer.score_to_status(56) == "Fair"
    assert scorer.score_to_status(75) == "Fair"
    assert scorer.score_to_status(76) == "Good"
    assert scorer.score_to_status(90) == "Good"
    assert scorer.score_to_status(91) == "Excellent"
    assert scorer.score_to_status(100) == "Excellent"
