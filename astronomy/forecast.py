"""
forecast.py

Policy for how far ahead a tracker projects and how densely it samples.

The horizon is a user choice, but the sampling step is not: reaching further
ahead widens the step so the request stays roughly the same size. A network
provider therefore pays no more for a month-long forecast than for a day, while
a provider that computes locally can afford a much larger budget and keep a
fine step over weeks.
"""

from __future__ import annotations

import math

# Selectable forecast horizons, as (label, minutes).
FORECAST_HORIZONS: tuple[tuple[str, int], ...] = (
    ("6 hours", 6 * 60),
    ("12 hours", 12 * 60),
    ("24 hours", 24 * 60),
    ("2 days", 2 * 24 * 60),
    ("3 days", 3 * 24 * 60),
    ("7 days", 7 * 24 * 60),
    ("14 days", 14 * 24 * 60),
    ("30 days", 30 * 24 * 60),
)

DEFAULT_HORIZON_MINUTES = 24 * 60

# Finest sampling interval. Long horizons coarsen this; nothing goes below it.
BASE_STEP_MINUTES = 5

# Refresh cadence at the 24-hour horizon, scaled proportionally from there.
BASE_REFRESH_SECONDS = 300


def step_for_horizon(horizon_minutes: int, max_samples: int) -> int:
    """Sampling interval that spans the horizon within a sample budget."""
    budget = max(1, int(max_samples))
    return max(BASE_STEP_MINUTES, math.ceil(max(0, horizon_minutes) / budget))


def refresh_seconds_for_horizon(horizon_minutes: int) -> int:
    """
    Re-request cadence for a horizon.

    A month-long forecast barely changes minute to minute, so it is refreshed
    far less often than a six-hour one.
    """
    scale = max(0, horizon_minutes) / DEFAULT_HORIZON_MINUTES
    return int(max(BASE_REFRESH_SECONDS, round(BASE_REFRESH_SECONDS * scale)))


def horizon_index(horizon_minutes: int) -> int:
    """Index of the closest selectable horizon, for seeding the UI control."""
    return min(
        range(len(FORECAST_HORIZONS)),
        key=lambda i: abs(FORECAST_HORIZONS[i][1] - horizon_minutes),
    )


def format_duration(minutes: int) -> str:
    """Render a horizon in whole days or hours for status text."""
    if minutes >= 24 * 60 and minutes % (24 * 60) == 0:
        return f"{minutes // (24 * 60)}d"
    if minutes >= 60:
        return f"{minutes // 60}h"
    return f"{minutes}min"
