from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

from astronomy.observation_scorer import ObservationScoreResult

T = TypeVar("T")


def score_series(
    samples: Iterable[T],
    evaluate_observation: Callable[[T], ObservationScoreResult],
) -> tuple[list[float], list[float]]:
    results = [evaluate_observation(sample) for sample in samples]
    observation_scores = [float(result.score) for result in results]
    weather_scores = [
        100.0 * float(result.subscores.get("weather", 0.0))
        for result in results
    ]
    return observation_scores, weather_scores
