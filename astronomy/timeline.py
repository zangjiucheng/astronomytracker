from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, Sequence, TypeVar

T = TypeVar("T")
TimelineKind = Literal["live", "history", "prediction"]


@dataclass(frozen=True)
class TimelineSelection(Generic[T]):
    kind: TimelineKind
    sample: T
    offset_minutes: int
    preview: bool


def _nearest_step_index(offset_minutes: int, step_minutes: int) -> int:
    step = max(1, int(step_minutes))
    minutes = abs(int(offset_minutes))
    return int((minutes + step / 2.0) // step)


def _clamp_index(index: int, length: int) -> int:
    return max(0, min(length - 1, index))


def select_timeline_sample(
    *,
    latest_sample: T,
    history_samples: Sequence[T],
    predicted_samples: Sequence[T],
    history_step_minutes: int,
    prediction_step_minutes: int,
    offset_minutes: int,
) -> TimelineSelection[T]:
    """Select the sample represented by a timeline offset.

    History samples are expected in chronological order. Prediction samples are
    expected from the forecast anchor forward.
    """
    offset = int(offset_minutes)
    if offset == 0:
        return TimelineSelection(
            kind="live",
            sample=latest_sample,
            offset_minutes=0,
            preview=False,
        )

    if offset < 0 and history_samples:
        delta_index = _nearest_step_index(offset, history_step_minutes)
        history_index = _clamp_index(
            len(history_samples) - 1 - delta_index,
            len(history_samples),
        )
        return TimelineSelection(
            kind="history",
            sample=history_samples[history_index],
            offset_minutes=offset,
            preview=True,
        )

    if offset > 0 and predicted_samples:
        prediction_index = _clamp_index(
            _nearest_step_index(offset, prediction_step_minutes),
            len(predicted_samples),
        )
        return TimelineSelection(
            kind="prediction",
            sample=predicted_samples[prediction_index],
            offset_minutes=offset,
            preview=True,
        )

    return TimelineSelection(
        kind="live",
        sample=latest_sample,
        offset_minutes=offset,
        preview=True,
    )
