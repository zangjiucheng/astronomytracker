from __future__ import annotations

from typing import Optional

from astronomy.math_utils import clamp
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

class BaseFallbackScorer(BaseObservationScorer):
    SCORE_WEIGHTS = {
        "sun": 0.25,
        "alt": 0.20,
        "elong": 0.15,
        "moon": 0.15,
        "weather": 0.25,
    }
