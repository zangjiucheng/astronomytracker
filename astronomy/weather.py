from __future__ import annotations

from typing import TYPE_CHECKING

from astronomy.math_utils import clamp

if TYPE_CHECKING:
    from astronomy.observation_scorer import ObservationContext


def score_cloud_cover(cloud_cover: float) -> float:
    cloud = clamp(cloud_cover / 100.0)
    return clamp((1.0 - cloud) ** 2)


def score_humidity_and_dew_point(temperature: float, dew_point: float) -> float:
    dew_spread = temperature - dew_point
    if dew_spread < 2.0:
        return 0.1
    if dew_spread < 5.0:
        return 0.4
    if dew_spread < 10.0:
        return 0.7
    return 1.0


def score_visibility_km(visibility_km: float) -> float:
    if visibility_km < 2.0:
        return 0.1
    if visibility_km < 5.0:
        return 0.35
    if visibility_km < 10.0:
        return 0.6
    if visibility_km < 15.0:
        return 0.8
    return 1.0


def score_wind(wind_speed: float) -> float:
    if wind_speed > 50.0:
        return 0.1
    if wind_speed > 30.0:
        return 0.35
    if wind_speed > 20.0:
        return 0.6
    if wind_speed > 10.0:
        return 0.8
    return 1.0


def score_seeing(seeing_arcsec: float | None) -> float:
    if seeing_arcsec is None:
        return 0.7
    if seeing_arcsec < 1.0:
        return 1.0
    if seeing_arcsec < 2.0:
        return 0.8
    if seeing_arcsec < 3.0:
        return 0.6
    if seeing_arcsec < 4.0:
        return 0.4
    return 0.2


def score_transparency(transparency: float | None) -> float:
    if transparency is None:
        return 0.7
    return clamp(transparency)


def score_weather_components(ctx: ObservationContext) -> dict[str, float]:
    s_cloud = score_cloud_cover(ctx.cloud_cover)
    s_humidity = score_humidity_and_dew_point(ctx.temperature, ctx.dew_point)
    s_visibility = score_visibility_km(max(0.0, ctx.visibility_km))
    s_wind = score_wind(max(0.0, ctx.wind_speed))
    s_seeing = score_seeing(ctx.seeing_arcsec)
    s_transparency = score_transparency(ctx.transparency)

    # Blend transparency and seeing into one optical-quality term.
    if ctx.transparency is None and ctx.seeing_arcsec is None:
        s_optical = 0.7
    elif ctx.transparency is None:
        s_optical = 0.5 * 0.7 + 0.5 * s_seeing
    elif ctx.seeing_arcsec is None:
        s_optical = s_transparency
    else:
        s_optical = 0.6 * s_transparency + 0.4 * s_seeing

    return {
        "cloud": s_cloud,
        "humidity": s_humidity,
        "visibility": s_visibility,
        "wind": s_wind,
        "seeing": s_seeing,
        "transparency": s_transparency,
        "optical": clamp(s_optical),
    }


def score_weather(ctx: ObservationContext) -> float:
    parts = score_weather_components(ctx)
    weather_score = (
        0.40 * parts["cloud"]
        + 0.20 * parts["humidity"]
        + 0.15 * parts["visibility"]
        + 0.10 * parts["wind"]
        + 0.15 * parts["optical"]
    )
    return clamp(weather_score)
