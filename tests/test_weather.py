from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from astronomy.observation_scorer import ObservationContext
from astronomy.weather import (
    score_cloud_cover,
    score_humidity_and_dew_point,
    score_seeing,
    score_transparency,
    score_visibility_km,
    score_wind,
    score_weather,
    score_weather_components,
)
from astronomy.math_utils import clamp


def test_weather_score_degrades_with_cloud_cover() -> None:
    clear_ctx = ObservationContext(
        target_alt=30.0, sun_alt=-18.0, solar_elongation=45.0, cloud_cover=0.0
    )
    cloudy_ctx = ObservationContext(
        target_alt=30.0, sun_alt=-18.0, solar_elongation=45.0, cloud_cover=90.0
    )

    assert score_weather(clear_ctx) > score_weather(cloudy_ctx)


def test_weather_components_include_expected_keys() -> None:
    ctx = ObservationContext(target_alt=40.0, sun_alt=-12.0, solar_elongation=60.0)
    parts = score_weather_components(ctx)
    assert {
        "cloud",
        "humidity",
        "visibility",
        "wind",
        "seeing",
        "transparency",
        "optical",
    }.issubset(parts)


def test_score_cloud_cover() -> None:
    assert score_cloud_cover(0.0) == 1.0
    assert score_cloud_cover(100.0) == 0.0
    assert 0.0 < score_cloud_cover(50.0) < 1.0


def test_score_cloud_cover_rejects_negative() -> None:
    result = score_cloud_cover(-10.0)
    assert result == 1.0


def test_score_humidity_and_dew_point() -> None:
    result_narrow = score_humidity_and_dew_point(10.0, 9.0)
    result_moderate = score_humidity_and_dew_point(10.0, 5.0)
    result_wide = score_humidity_and_dew_point(10.0, 0.0)

    assert result_narrow == 0.1
    assert result_moderate == 0.7
    assert result_wide == 1.0


def test_score_visibility_km() -> None:
    assert score_visibility_km(0.0) == 0.1
    assert score_visibility_km(20.0) == 1.0
    assert 0.0 < score_visibility_km(7.0) < 1.0


def test_score_wind() -> None:
    assert score_wind(0.0) == 1.0
    assert score_wind(15.0) == 0.8
    assert score_wind(55.0) == 0.1


def test_score_seeing_defaults_to_07() -> None:
    assert score_seeing(None) == 0.7


def test_score_seeing_scales_with_arcsec() -> None:
    assert score_seeing(0.5) == 1.0
    assert score_seeing(2.5) == 0.6
    assert score_seeing(5.0) == 0.2


def test_score_transparency_defaults_to_07() -> None:
    assert score_transparency(None) == 0.7


def test_score_transparency_clamped() -> None:
    assert score_transparency(1.5) == 1.0
    assert score_transparency(-0.5) == 0.0


def test_score_weather_is_clamped() -> None:
    ctx = ObservationContext(target_alt=45.0, sun_alt=-18.0, solar_elongation=50.0)
    result = score_weather(ctx)
    assert 0.0 <= result <= 1.0


def test_score_weather_penalizes_high_humidity() -> None:
    ctx_low_humidity = ObservationContext(
        target_alt=45.0,
        sun_alt=-18.0,
        solar_elongation=50.0,
        temperature=20.0,
        dew_point=5.0,
    )
    ctx_high_humidity = ObservationContext(
        target_alt=45.0,
        sun_alt=-18.0,
        solar_elongation=50.0,
        temperature=20.0,
        dew_point=19.0,
    )

    assert score_weather(ctx_low_humidity) > score_weather(ctx_high_humidity)


def test_score_weather_penalizes_strong_wind() -> None:
    ctx_calm = ObservationContext(
        target_alt=45.0, sun_alt=-18.0, solar_elongation=50.0, wind_speed=5.0
    )
    ctx_windy = ObservationContext(
        target_alt=45.0, sun_alt=-18.0, solar_elongation=50.0, wind_speed=35.0
    )

    assert score_weather(ctx_calm) > score_weather(ctx_windy)


def test_weather_components_optical_blends_transparency_and_seeing() -> None:
    ctx_transp = ObservationContext(
        target_alt=45.0, sun_alt=-18.0, solar_elongation=50.0, transparency=1.0
    )
    ctx_seeing = ObservationContext(
        target_alt=45.0, sun_alt=-18.0, solar_elongation=50.0, seeing_arcsec=1.0
    )
    ctx_both = ObservationContext(
        target_alt=45.0,
        sun_alt=-18.0,
        solar_elongation=50.0,
        transparency=1.0,
        seeing_arcsec=1.0,
    )

    parts_transp = score_weather_components(ctx_transp)
    parts_seeing = score_weather_components(ctx_seeing)
    parts_both = score_weather_components(ctx_both)

    assert parts_transp["optical"] == 1.0
    assert parts_seeing["optical"] == 0.75
    assert 0.0 <= parts_both["optical"] <= 1.0
