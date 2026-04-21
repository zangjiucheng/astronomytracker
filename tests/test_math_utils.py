from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from astronomy.math_utils import clamp


def test_clamp_defaults() -> None:
    assert clamp(5.0) == 1.0
    assert clamp(-5.0) == 0.0
    assert clamp(0.5) == 0.5


def test_clamp_respects_bounds() -> None:
    assert clamp(0.5, 0.0, 1.0) == 0.5
    assert clamp(-10.0, 0.0, 1.0) == 0.0
    assert clamp(10.0, 0.0, 1.0) == 1.0


def test_clamp_custom_bounds() -> None:
    assert clamp(5.0, lo=-10.0, hi=10.0) == 5.0
    assert clamp(-20.0, lo=-10.0, hi=10.0) == -10.0
    assert clamp(20.0, lo=-10.0, hi=10.0) == 10.0
