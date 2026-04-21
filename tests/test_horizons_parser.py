from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from astronomy.horizons_parser import HorizonsParser
from astronomy.tracker_state import HorizonsError, HorizonsParseError


def _make_horizons_response(lines: list[str]) -> str:
    return "\n".join(lines)


def test_parse_rejects_no_matches_found() -> None:
    parser = HorizonsParser()
    text = _make_horizons_response(
        [
            "JPL Horizons API",
            "No matches found.",
        ]
    )

    try:
        parser.parse(text)
        assert False, "Should have raised HorizonsError"
    except HorizonsError:
        pass


def test_parse_rejects_missing_soe_marker() -> None:
    parser = HorizonsParser()
    text = _make_horizons_response(
        [
            "JPL Horizons API",
            "$$EOE",
        ]
    )

    try:
        parser.parse(text)
        assert False, "Should have raised HorizonsParseError"
    except HorizonsParseError:
        pass


def test_parse_rejects_malformed_eoe_before_soe() -> None:
    parser = HorizonsParser()
    text = _make_horizons_response(
        [
            "$$EOE",
            "$$SOE",
            "data",
        ]
    )

    try:
        parser.parse(text)
        assert False, "Should have raised HorizonsParseError"
    except HorizonsParseError:
        pass


def test_parse_rejects_missing_header() -> None:
    parser = HorizonsParser()
    text = _make_horizons_response(
        [
            "Some other content.",
            "$$SOE",
            "2025-Jan-01 00:00:00, , , 123.0,45.0,30.0,0.5,10.0,50.0",
            "$$EOE",
        ]
    )

    try:
        parser.parse(text)
        assert False, "Should have raised HorizonsParseError"
    except HorizonsParseError:
        pass
