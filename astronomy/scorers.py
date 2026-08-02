from __future__ import annotations

import math
from typing import Optional

from astronomy.math_utils import clamp
from astronomy.meteor_showers import (
    MeteorShower,
    UnknownShowerError,
    get_shower,
    observed_hourly_rate,
)
from astronomy.observation_scorer import BaseObservationScorer, ObservationContext


class NearSolarCometScorer(BaseObservationScorer):
    """
    Scorer specialized for near-solar comets.
    Strongly penalizes daylight and low solar elongation.
    """
    SCORE_WEIGHTS = {
        "sun": 0.35,
        "elong": 0.25,
        "alt": 0.20,
        "moon": 0.10,
        "weather": 0.10,
    }


    def check_hard_gates(self, ctx: ObservationContext) -> Optional[str]:
        if ctx.target_alt <= 0:
            return "Target below horizon"
        if ctx.sun_alt > 0:
            return "Sun above horizon"
        if ctx.solar_elongation < 8:
            return "Target too close to the Sun"
        return None

class DeepSkyScorer(BaseObservationScorer):
    """
    Scorer for galaxies, nebulae, clusters, and other deep-sky objects.
    """

    SCORE_WEIGHTS = {
        "sun": 0.23,
        "alt": 0.18,
        "elong": 0.04,
        "moon": 0.18,
        "weather": 0.27,
        "env": 0.10,
    }

    def check_hard_gates(self, ctx: ObservationContext) -> Optional[str]:
        if ctx.target_alt <= 0:
            return "Target below horizon"
        if ctx.sun_alt > -6:
            return "Sky too bright for deep-sky observation"
        return None

    def score_environment(self, ctx: ObservationContext) -> float:
        # Deep-sky viewing is very sensitive to light pollution.
        cloud_score = clamp(1.0 - ctx.cloud_cover / 100.0)
        lp_score = 1.0 if ctx.bortle is None else clamp(1.0 - (ctx.bortle - 1.0) / 8.0)
        return 0.45 * cloud_score + 0.55 * lp_score

    def compute_subscores(self, ctx: ObservationContext) -> dict[str, float]:
        subscores = super().compute_subscores(ctx)
        subscores["env"] = self.score_environment(ctx)
        return subscores

    def build_reasons(self, ctx: ObservationContext, subscores: dict[str, float]) -> list[str]:
        reasons = super().build_reasons(ctx, subscores)
        if subscores.get("env", 1.0) < 0.5:
            reasons.append("Cloud cover or light pollution is limiting visibility")
        if ctx.sun_alt > -12:
            reasons.append("Deep-sky observation benefits from astronomical darkness")
        return reasons


class PlanetScorer(BaseObservationScorer):
    """
    Scorer for bright planets.
    Planets are more tolerant of twilight and some moonlight.
    """

    SCORE_WEIGHTS = {
        "sun": 0.20,
        "alt": 0.30,
        "elong": 0.15,
        "moon": 0.15,
        "weather": 0.20,
    }

    def check_hard_gates(self, ctx: ObservationContext) -> Optional[str]:
        if ctx.target_alt <= 0:
            return "Target below horizon"
        if ctx.sun_alt > 5:
            return "Daylight too strong for practical observation"
        return None

class MoonScorer(BaseObservationScorer):
    """
    Scorer specialized for Moon tracking.
    Moonlight interference is not considered a penalty for the Moon itself.
    """

    SCORE_WEIGHTS = {
        "sun": 0.25,
        "alt": 0.35,
        "elong": 0.20,
        "weather": 0.20,
    }

    def check_hard_gates(self, ctx: ObservationContext) -> Optional[str]:
        if ctx.target_alt <= 0:
            return "Target below horizon"
        if ctx.sun_alt > 10:
            return "Daylight too strong for practical moon observation"
        return None

    def score_moon(self, ctx: ObservationContext) -> float:
        _ = ctx
        return 1.0

class MeteorShowerScorer(BaseObservationScorer):
    """
    Scorer for meteor showers, which are rated differently from point targets.

    Three things make a shower unlike every other target in this project:

    - Meteors appear all over the sky, so the angular distance between the
      radiant and the Moon is irrelevant; only how much the Moon brightens the
      whole sky matters. Solar elongation is meaningless for the same reason.
    - The rate scales with the sine of the radiant's altitude, which is a
      physical relation rather than a preference, so it replaces the generic
      altitude curve.
    - The date matters independently of the geometry. A perfectly placed
      radiant on a perfectly clear night is still a quiet night two weeks off
      the stream's peak.
    """

    SCORE_WEIGHTS = {
        "sun": 0.18,
        "alt": 0.22,
        "moon": 0.20,
        "weather": 0.20,
        "activity": 0.20,
    }

    # Naked-eye limiting magnitude assumed for a clear, moonless sky when the
    # site's light pollution is unknown. Roughly an outer-suburban sky.
    DEFAULT_LIMITING_MAGNITUDE = 6.0

    _LIMITING_NAMES = {
        "sun": "twilight / sky brightness",
        "alt": "radiant altitude",
        "moon": "moonlight",
        "weather": "weather conditions",
        "activity": "distance from the shower peak",
    }

    def __init__(self, shower: Optional[MeteorShower] = None) -> None:
        self.shower = shower

    def resolve_shower(self, ctx: ObservationContext) -> Optional[MeteorShower]:
        if self.shower is not None:
            return self.shower
        if not ctx.target_name:
            return None
        try:
            return get_shower(ctx.target_name)
        except UnknownShowerError:
            return None

    def check_hard_gates(self, ctx: ObservationContext) -> Optional[str]:
        if ctx.sun_alt > -6.0:
            return "Sky too bright for meteors"
        if ctx.target_alt <= 0.0:
            return "Radiant below horizon"
        return None

    def compute_subscores(self, ctx: ObservationContext) -> dict[str, float]:
        # Deliberately omits the solar elongation term: it says nothing about a
        # shower, and leaving it in would let it be reported as the limiting
        # factor.
        return {
            "sun": self.score_sun(ctx),
            "alt": self.score_alt(ctx),
            "moon": self.score_moon(ctx),
            "weather": self.score_weather(ctx),
            "activity": self.score_activity(ctx),
        }

    def score_alt(self, ctx: ObservationContext) -> float:
        # Observed rate is proportional to sin(radiant altitude).
        return clamp(math.sin(math.radians(max(0.0, ctx.target_alt))))

    def score_moon(self, ctx: ObservationContext) -> float:
        if ctx.moon_alt <= 0.0:
            return 1.0
        height_factor = clamp(ctx.moon_alt / 40.0)
        penalty = 0.9 * ctx.moon_illumination * (0.35 + 0.65 * height_factor)
        return clamp(1.0 - penalty)

    def score_activity(self, ctx: ObservationContext) -> float:
        shower = self.resolve_shower(ctx)
        if shower is None or ctx.observation_time is None:
            return 1.0
        peak = shower.peak_zhr
        if peak <= 0.0:
            return 1.0
        return clamp(shower.zhr_at(ctx.observation_time) / peak)

    def limiting_magnitude(self, ctx: ObservationContext) -> float:
        """Estimated naked-eye limiting magnitude, used to scale the rate."""
        if ctx.bortle is None:
            magnitude = self.DEFAULT_LIMITING_MAGNITUDE
        else:
            magnitude = 7.8 - 0.45 * (ctx.bortle - 1.0)
        if ctx.moon_alt > 0.0:
            height_factor = clamp(ctx.moon_alt / 40.0)
            magnitude -= 2.5 * ctx.moon_illumination * (0.3 + 0.7 * height_factor)
        return clamp(magnitude, 2.0, 7.8)

    def compute_custom_scores(
        self,
        ctx: ObservationContext,
        subscores: dict[str, float],
        final_score: int,
    ) -> dict[str, float]:
        _ = (subscores, final_score)
        shower = self.resolve_shower(ctx)
        if shower is None or ctx.observation_time is None:
            return {}
        zhr = shower.zhr_at(ctx.observation_time)
        magnitude = self.limiting_magnitude(ctx)
        rate = observed_hourly_rate(
            zhr=zhr,
            radiant_altitude_deg=ctx.target_alt,
            limiting_magnitude=magnitude,
            population_index=shower.population_index,
            obstructed_sky_fraction=clamp(ctx.cloud_cover / 100.0),
        )
        return {
            "meteors/hr": round(rate, 1),
            "ZHR": round(zhr, 1),
            "limiting mag": round(magnitude, 1),
        }

    def build_reasons(
        self, ctx: ObservationContext, subscores: dict[str, float]
    ) -> list[str]:
        reasons: list[str] = []
        shower = self.resolve_shower(ctx)

        if shower is not None and ctx.observation_time is not None:
            days = shower.days_from_peak(ctx.observation_time)
            if abs(days) < 0.5:
                reasons.append(f"At the {shower.name} peak")
            else:
                when = "before" if days < 0 else "after"
                reasons.append(f"{abs(days):.1f} days {when} the {shower.name} peak")

        if subscores.get("alt", 1.0) < 0.35:
            reasons.append(
                f"Radiant is low ({ctx.target_alt:.0f} deg), suppressing the rate; "
                "the few meteors seen will be long earthgrazers"
            )
        if subscores.get("moon", 1.0) < 0.6:
            reasons.append(
                f"Moon is up ({ctx.moon_illumination * 100:.0f}% lit) and washing out "
                "fainter meteors"
            )
        if ctx.sun_alt > -18.0:
            reasons.append("Not yet astronomically dark")
        if ctx.cloud_cover > 30.0:
            reasons.append(f"Cloud cover {ctx.cloud_cover:.0f}% is blocking sky")
        if ctx.bortle is None:
            reasons.append(
                f"Rate assumes a magnitude {self.DEFAULT_LIMITING_MAGNITUDE:.1f} sky; "
                "darker skies give more"
            )
        return reasons

    def find_limiting_factor(self, subscores: dict[str, float]) -> Optional[str]:
        if not subscores:
            return None
        if subscores.get("weather", 0.5) < 0.4:
            return self._LIMITING_NAMES["weather"]
        key = min(subscores, key=lambda metric: subscores[metric])
        return self._LIMITING_NAMES.get(key, key)


class BaseFallbackScorer(BaseObservationScorer):
    SCORE_WEIGHTS = {
        "sun": 0.25,
        "alt": 0.20,
        "elong": 0.15,
        "moon": 0.15,
        "weather": 0.25,
    }
