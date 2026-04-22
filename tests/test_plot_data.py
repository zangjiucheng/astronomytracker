from __future__ import annotations

from dataclasses import dataclass

from astronomy.plot_data import score_series


@dataclass
class _Result:
    score: int
    subscores: dict[str, float]


def test_score_series_evaluates_each_sample_once() -> None:
    calls: list[str] = []

    def evaluate(sample: str) -> _Result:
        calls.append(sample)
        return _Result(score=len(calls) * 10, subscores={"weather": 0.5})

    observation_scores, weather_scores = score_series(["a", "b", "c"], evaluate)

    assert calls == ["a", "b", "c"]
    assert observation_scores == [10.0, 20.0, 30.0]
    assert weather_scores == [50.0, 50.0, 50.0]
