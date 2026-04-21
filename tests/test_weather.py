from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from astronomy.observation_scorer import ObservationContext
from astronomy.weather import score_weather, score_weather_components


def test_weather_score_degrades_with_cloud_cover() -> None:
    clear_ctx = ObservationContext(target_alt=30.0, sun_alt=-18.0, solar_elongation=45.0, cloud_cover=0.0)
    cloudy_ctx = ObservationContext(target_alt=30.0, sun_alt=-18.0, solar_elongation=45.0, cloud_cover=90.0)

    assert score_weather(clear_ctx) > score_weather(cloudy_ctx)


def test_weather_components_include_expected_keys() -> None:
    ctx = ObservationContext(target_alt=40.0, sun_alt=-12.0, solar_elongation=60.0)
    parts = score_weather_components(ctx)
    assert {"cloud", "humidity", "visibility", "wind", "seeing", "transparency", "optical"}.issubset(parts)
