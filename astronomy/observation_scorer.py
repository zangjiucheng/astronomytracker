from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class ObservationContext:
    target_alt: float
    sun_alt: float
    solar_elongation: float

    moon_alt: float = -90.0
    moon_illumination: float = 0.0
    moon_separation: float = 180.0

    cloud_cover: Optional[float] = None
    bortle: Optional[float] = None

    azimuth: Optional[float] = None
    magnitude: Optional[float] = None
    target_name: Optional[str] = None


@dataclass
class ObservationScoreResult:
    score: int
    status: str
    observable: bool
    reasons: list[str] = field(default_factory=list)
    subscores: dict[str, float] = field(default_factory=dict)
    custom_scores: dict[str, float] = field(default_factory=dict)
    limiting_factor: Optional[str] = None


class BaseObservationScorer(ABC):
    """
    Abstract base scorer for astronomical observation conditions.

    Subclasses may override:
    - hard gate rules
    - weighting
    - subscore formulas
    - custom score dimensions
    - status mapping
    - reason generation
    """

    def evaluate(self, ctx: ObservationContext) -> ObservationScoreResult:
        gate = self.check_hard_gates(ctx)
        if gate is not None:
            return ObservationScoreResult(
                score=0,
                status="Not observable",
                observable=False,
                reasons=[gate],
                subscores={},
                limiting_factor=gate,
            )

        subscores = self.compute_subscores(ctx)
        raw_score = self.combine_subscores(subscores, ctx)
        score = int(round(clamp(raw_score / 100.0) * 100.0))

        status = self.score_to_status(score)
        reasons = self.build_reasons(ctx, subscores)
        custom_scores = self.compute_custom_scores(ctx, subscores, score)
        limiting_factor = self.find_limiting_factor(subscores)

        return ObservationScoreResult(
            score=score,
            status=status,
            observable=score > 15,
            reasons=reasons,
            subscores=subscores,
            custom_scores=custom_scores,
            limiting_factor=limiting_factor,
        )

    def check_hard_gates(self, ctx: ObservationContext) -> Optional[str]:
        """
        Return a blocking reason if the target is definitely not observable.
        Default implementation can be overridden by subclasses.
        """
        if ctx.target_alt <= 0:
            return "Target below horizon"
        return None

    def compute_subscores(self, ctx: ObservationContext) -> dict[str, float]:
        return {
            "sun": self.score_sun(ctx),
            "alt": self.score_alt(ctx),
            "elong": self.score_elongation(ctx),
            "moon": self.score_moon(ctx),
            "env": self.score_environment(ctx),
        }

    def compute_custom_scores(
        self,
        ctx: ObservationContext,
        subscores: dict[str, float],
        final_score: int,
    ) -> dict[str, float]:
        """
        Optional extension point for project-specific metrics.

        Return additional normalized (0..100 recommended) scores such as:
        - imaging_quality
        - binocular_visibility
        - stability_index
        """
        _ = (ctx, subscores, final_score)
        return {}

    @abstractmethod
    def combine_subscores(self, subscores: dict[str, float], ctx: ObservationContext) -> float:
        """
        Return a raw score in [0, 100].
        """
        raise NotImplementedError

    def score_sun(self, ctx: ObservationContext) -> float:
        sun_alt = ctx.sun_alt
        if sun_alt > 0:
            return 0.0
        if sun_alt > -6:
            return 0.15
        if sun_alt > -12:
            return 0.45
        if sun_alt > -18:
            return 0.75
        return 1.0

    def score_alt(self, ctx: ObservationContext) -> float:
        alt = ctx.target_alt
        if alt <= 0:
            return 0.0
        if alt <= 5:
            return 0.15 * (alt / 5.0)
        if alt <= 15:
            return 0.15 + 0.35 * ((alt - 5.0) / 10.0)
        if alt <= 30:
            return 0.50 + 0.30 * ((alt - 15.0) / 15.0)
        return 0.80 + 0.20 * ((min(alt, 60.0) - 30.0) / 30.0)

    def score_elongation(self, ctx: ObservationContext) -> float:
        elongation = ctx.solar_elongation
        if elongation < 10:
            return 0.0
        if elongation < 15:
            return 0.10 * ((elongation - 10.0) / 5.0)
        if elongation < 25:
            return 0.10 + 0.30 * ((elongation - 15.0) / 10.0)
        if elongation < 40:
            return 0.40 + 0.35 * ((elongation - 25.0) / 15.0)
        return 0.75 + 0.25 * ((min(elongation, 70.0) - 40.0) / 30.0)

    def score_moon(self, ctx: ObservationContext) -> float:
        if ctx.moon_alt <= 0:
            return 1.0
        penalty = 0.7 * ctx.moon_illumination * max(0.0, 1.0 - ctx.moon_separation / 90.0)
        return clamp(1.0 - penalty)

    def score_environment(self, ctx: ObservationContext) -> float:
        cloud_score = 1.0 if ctx.cloud_cover is None else clamp(1.0 - ctx.cloud_cover / 100.0)
        lp_score = 1.0 if ctx.bortle is None else clamp(1.0 - (ctx.bortle - 1.0) / 8.0)
        return 0.7 * cloud_score + 0.3 * lp_score

    def score_to_status(self, score: int) -> str:
        if score <= 15:
            return "Not observable"
        if score <= 35:
            return "Very poor"
        if score <= 55:
            return "Poor"
        if score <= 75:
            return "Fair"
        if score <= 90:
            return "Good"
        return "Excellent"

    def build_reasons(self, ctx: ObservationContext, subscores: dict[str, float]) -> list[str]:
        reasons: list[str] = []
        if subscores["sun"] < 0.3:
            reasons.append("Sky is too bright due to the Sun")
        if subscores["elong"] < 0.3:
            reasons.append("Target is too close to the Sun")
        if subscores["alt"] < 0.3:
            reasons.append("Target is too low above the horizon")
        if subscores["moon"] < 0.5:
            reasons.append("Moonlight interference is significant")
        if subscores["env"] < 0.5:
            reasons.append("Cloud cover or light pollution is limiting visibility")
        return reasons

    def find_limiting_factor(self, subscores: dict[str, float]) -> Optional[str]:
        if not subscores:
            return None
        key = min(subscores, key=lambda metric: subscores[metric])
        mapping = {
            "sun": "solar altitude / sky brightness",
            "alt": "target altitude",
            "elong": "solar elongation",
            "moon": "moonlight interference",
            "env": "environmental conditions",
        }
        return mapping.get(key, key)


class NearSolarCometScorer(BaseObservationScorer):
    """
    Scorer specialized for near-solar comets.
    Strongly penalizes daylight and low solar elongation.
    """

    def check_hard_gates(self, ctx: ObservationContext) -> Optional[str]:
        if ctx.target_alt <= 0:
            return "Target below horizon"
        if ctx.sun_alt > 0:
            return "Sun above horizon"
        if ctx.solar_elongation < 8:
            return "Target too close to the Sun"
        return None

    def combine_subscores(self, subscores: dict[str, float], ctx: ObservationContext) -> float:
        return 100.0 * (
            0.35 * subscores["sun"]
            + 0.25 * subscores["elong"]
            + 0.20 * subscores["alt"]
            + 0.10 * subscores["moon"]
            + 0.10 * subscores["env"]
        )


class DeepSkyScorer(BaseObservationScorer):
    """
    Scorer for galaxies, nebulae, clusters, and other deep-sky objects.
    """

    def check_hard_gates(self, ctx: ObservationContext) -> Optional[str]:
        if ctx.target_alt <= 0:
            return "Target below horizon"
        if ctx.sun_alt > -6:
            return "Sky too bright for deep-sky observation"
        return None

    def score_environment(self, ctx: ObservationContext) -> float:
        # Deep-sky viewing is very sensitive to light pollution.
        cloud_score = 1.0 if ctx.cloud_cover is None else clamp(1.0 - ctx.cloud_cover / 100.0)
        lp_score = 1.0 if ctx.bortle is None else clamp(1.0 - (ctx.bortle - 1.0) / 8.0)
        return 0.45 * cloud_score + 0.55 * lp_score

    def combine_subscores(self, subscores: dict[str, float], ctx: ObservationContext) -> float:
        return 100.0 * (
            0.35 * subscores["sun"]
            + 0.20 * subscores["alt"]
            + 0.05 * subscores["elong"]
            + 0.20 * subscores["moon"]
            + 0.20 * subscores["env"]
        )

    def build_reasons(self, ctx: ObservationContext, subscores: dict[str, float]) -> list[str]:
        reasons = super().build_reasons(ctx, subscores)
        if ctx.sun_alt > -12:
            reasons.append("Deep-sky observation benefits from astronomical darkness")
        return reasons


class PlanetScorer(BaseObservationScorer):
    """
    Scorer for bright planets.
    Planets are more tolerant of twilight and some moonlight.
    """

    def check_hard_gates(self, ctx: ObservationContext) -> Optional[str]:
        if ctx.target_alt <= 0:
            return "Target below horizon"
        if ctx.sun_alt > 5:
            return "Daylight too strong for practical observation"
        return None

    def combine_subscores(self, subscores: dict[str, float], ctx: ObservationContext) -> float:
        return 100.0 * (
            0.20 * subscores["sun"]
            + 0.35 * subscores["alt"]
            + 0.15 * subscores["elong"]
            + 0.10 * subscores["moon"]
            + 0.20 * subscores["env"]
        )


class BaseFallbackScorer(BaseObservationScorer):
    def combine_subscores(self, subscores: dict[str, float], ctx: ObservationContext) -> float:
        return 100.0 * (
            0.30 * subscores["sun"]
            + 0.25 * subscores["alt"]
            + 0.20 * subscores["elong"]
            + 0.15 * subscores["moon"]
            + 0.10 * subscores["env"]
        )