from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from astronomy.observation_scorer import ObservationContext
from astronomy.scorers import BaseFallbackScorer, DeepSkyScorer, MoonScorer


def test_base_fallback_subscores_do_not_include_env() -> None:
    scorer = BaseFallbackScorer()
    ctx = ObservationContext(target_alt=35.0, sun_alt=-14.0, solar_elongation=50.0)

    subscores = scorer.compute_subscores(ctx)
    assert "env" not in subscores


def test_deep_sky_subscores_include_env() -> None:
    scorer = DeepSkyScorer()
    ctx = ObservationContext(target_alt=35.0, sun_alt=-14.0, solar_elongation=50.0, bortle=8.0)

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
