from __future__ import annotations

from typing import Callable

from astronomy.observation_scorer import BaseObservationScorer
from astronomy.scorers import (
    BaseFallbackScorer,
    DeepSkyScorer,
    MoonScorer,
    NearSolarCometScorer,
    PlanetScorer,
)


ScorerFactory = Callable[[], BaseObservationScorer]


_SCORER_REGISTRY: dict[str, ScorerFactory] = {
    "near_solar_comet": NearSolarCometScorer,
    "deep_sky": DeepSkyScorer,
    "planet": PlanetScorer,
    "moon": MoonScorer,
}


def register_scorer(target_type: str, scorer_factory: ScorerFactory) -> None:
    """
    Register or override a scorer factory for a target type.

    Example:
        register_scorer("asteroid", AsteroidScorer)
    """
    normalized = target_type.strip().lower()
    if not normalized:
        raise ValueError("target_type cannot be empty")
    _SCORER_REGISTRY[normalized] = scorer_factory


def get_registered_target_types() -> tuple[str, ...]:
    """Return all registered target types for UI/config selection."""
    return tuple(sorted(_SCORER_REGISTRY.keys()))


def create_scorer(target_type: str) -> BaseObservationScorer:
    normalized = target_type.strip().lower()
    scorer_factory = _SCORER_REGISTRY.get(normalized, BaseFallbackScorer)
    return scorer_factory()