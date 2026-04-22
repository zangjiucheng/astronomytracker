from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from typing import Callable

from astronomy.tracker_state import (
    EphemerisSample,
    HorizonsError,
    HorizonsParseError,
    compass_from_azimuth,
)


def _normalize_token(token: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", token.lower())


def _parse_horizons_timestamp(raw_value: str) -> datetime:
    cleaned = raw_value.strip()
    if cleaned.startswith("b"):
        cleaned = cleaned[1:].strip()

    candidates = [
        "%Y-%b-%d %H:%M:%S.%f",
        "%Y-%b-%d %H:%M:%S",
        "%Y-%b-%d %H:%M",
    ]
    for fmt in candidates:
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    raise HorizonsParseError(f"Unable to parse Horizons timestamp: {raw_value!r}")


class HorizonsParser:
    """Parse Horizons observer tables using explicit column labels.

    The CSV-like observer output includes the time tag, solar/interfering-body
    presence markers, and then the requested quantity columns. We locate the
    header row and map column positions by label so we do not rely on numeric
    fields appearing in a fixed order.
    """

    def parse(self, response_text: str) -> EphemerisSample:
        try:
            samples = self.parse_many(response_text)
        except HorizonsError:
            raise
        if not samples:
            raise HorizonsParseError("Horizons response contains no data rows.")
        return samples[0]

    def parse_many(self, response_text: str) -> list[EphemerisSample]:
        non_ephemeris_indicators = [
            "No matches found",
            "Matching small-bodies",
            "Unknown object",
            "Invalid object",
            "object not found",
            "unable to resolve",
            "Multiple major-bodies match",
            "Multiple minor-bodies match",
        ]
        for indicator in non_ephemeris_indicators:
            if indicator.lower() in response_text.lower():
                raise HorizonsError(
                    f"Horizons could not resolve the target object.\n{response_text}"
                )

        lines = response_text.splitlines()
        start_index = self._find_marker_index(lines, "$$SOE")
        end_index = self._find_marker_index(lines, "$$EOE")
        if end_index <= start_index:
            raise HorizonsParseError(
                "Horizons response is malformed: $$EOE appears before $$SOE."
            )

        header_line = self._find_header_line(lines[:start_index])
        header_tokens = self._split_csv_line(header_line)
        indices = self._map_header_indices(header_tokens)
        data_lines = [
            line for line in lines[start_index + 1 : end_index] if line.strip()
        ]
        if not data_lines:
            raise HorizonsParseError("Horizons response contains no data rows.")

        return [self._parse_data_line(data_line, indices) for data_line in data_lines]

    def _find_marker_index(self, lines: list[str], marker: str) -> int:
        for index, line in enumerate(lines):
            if marker in line:
                return index
        sample = "\n".join(lines[:20])
        raise HorizonsParseError(
            f"Could not find {marker} in Horizons response:\n{sample}"
        )

    def _find_header_line(self, lines: list[str]) -> str:
        for line in reversed(lines[-50:]):
            if (
                "Date__" in line
                and "R.A." in line
                and "Azimuth" in line
                and "Elevation" in line
            ):
                return line
        raise HorizonsParseError(
            "Could not locate Horizons observer table header line."
        )

    def _find_first_data_line(self, lines: list[str]) -> str:
        for line in lines:
            if line.strip():
                return line
        raise HorizonsParseError("Horizons response contains no data rows.")

    def _parse_data_line(
        self, data_line: str, indices: dict[str, int]
    ) -> EphemerisSample:
        row_tokens = self._split_csv_line(data_line)
        self._validate_row_length(row_tokens, indices)

        try:
            utc_time = _parse_horizons_timestamp(row_tokens[indices["time"]])
            ra_deg = float(row_tokens[indices["ra"]])
            dec_deg = float(row_tokens[indices["dec"]])
            az_deg = float(row_tokens[indices["az"]])
            el_deg = float(row_tokens[indices["el"]])
            range_au = float(row_tokens[indices["delta"]])
            range_rate_kms = float(row_tokens[indices["deldot"]])
            solar_elong_deg = float(row_tokens[indices["solar_elong"]])
            solar_presence = self._safe_token(row_tokens, indices["solar_presence"])
            interferer_presence = self._safe_token(
                row_tokens, indices["interferer_presence"]
            )
            solar_alignment_code = self._safe_token(
                row_tokens, indices["solar_alignment_code"]
            )
        except (ValueError, IndexError) as exc:
            raise HorizonsParseError(
                f"Failed to parse Horizons data row:\n{data_line}\n{exc}"
            ) from exc

        # These validations prevent silently accepting shifted or malformed columns.
        if not (-90.0 <= dec_deg <= 90.0):
            raise HorizonsParseError(
                f"Invalid declination value {dec_deg}; expected -90..90 degrees."
            )
        if not (0.0 <= az_deg <= 360.0):
            raise HorizonsParseError(
                f"Invalid azimuth value {az_deg}; expected 0..360 degrees."
            )
        if not (-90.0 <= el_deg <= 90.0):
            raise HorizonsParseError(
                f"Invalid elevation value {el_deg}; expected -90..90 degrees."
            )
        if not (0.0 <= solar_elong_deg <= 180.0):
            raise HorizonsParseError(
                f"Invalid solar elongation value {solar_elong_deg}; expected 0..180 degrees."
            )

        local_time = utc_time.astimezone()
        visibility_status = "Above horizon" if el_deg > 0.0 else "Below horizon"

        return EphemerisSample(
            utc_time=utc_time,
            local_time=local_time,
            ra_deg=ra_deg,
            dec_deg=dec_deg,
            az_deg=az_deg,
            el_deg=el_deg,
            solar_elong_deg=solar_elong_deg,
            compass_direction=compass_from_azimuth(az_deg),
            visibility_status=visibility_status,
            range_au=range_au,
            range_rate_kms=range_rate_kms,
            solar_presence=solar_presence,
            interferer_presence=interferer_presence,
            solar_alignment_code=solar_alignment_code,
        )

    def _split_csv_line(self, line: str) -> list[str]:
        return [token.strip() for token in next(csv.reader([line]))]

    def _map_header_indices(self, header_tokens: list[str]) -> dict[str, int]:
        def first_index(predicate: Callable[[str, str], bool], label: str) -> int:
            for index, token in enumerate(header_tokens):
                if predicate(token, _normalize_token(token)):
                    return index
            raise HorizonsParseError(
                f"Could not locate '{label}' in Horizons header: {header_tokens}"
            )

        time_index = first_index(lambda raw, norm: norm.startswith("date"), "time")
        solar_presence_index = time_index + 1
        interferer_presence_index = time_index + 2

        return {
            "time": time_index,
            "solar_presence": solar_presence_index,
            "interferer_presence": interferer_presence_index,
            "ra": first_index(lambda raw, norm: norm.startswith("ra"), "RA"),
            "dec": first_index(lambda raw, norm: norm.startswith("dec"), "Dec"),
            "az": first_index(lambda raw, norm: "azimuth" in norm, "Azimuth"),
            "el": first_index(lambda raw, norm: "elevation" in norm, "Elevation"),
            "delta": first_index(lambda raw, norm: norm == "delta", "delta"),
            "deldot": first_index(lambda raw, norm: norm == "deldot", "deldot"),
            "solar_elong": first_index(
                lambda raw, norm: norm == "sot", "solar elongation"
            ),
            "solar_alignment_code": first_index(
                lambda raw, norm: (
                    norm in {"r", "l", "t", "?"} or raw.strip().startswith("/")
                ),
                "/r code",
            ),
        }

    def _validate_row_length(
        self, row_tokens: list[str], indices: dict[str, int]
    ) -> None:
        needed_index = max(indices.values())
        if len(row_tokens) <= needed_index:
            raise HorizonsParseError(
                f"Horizons data row is too short for the requested columns.\nRow: {row_tokens}\nIndices: {indices}"
            )

    def _safe_token(self, row_tokens: list[str], index: int) -> str:
        if index >= len(row_tokens):
            return ""
        return row_tokens[index].strip()
