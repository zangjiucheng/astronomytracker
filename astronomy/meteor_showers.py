"""
meteor_showers.py

Radiant and activity data for the major annual meteor showers.

A meteor shower has no Horizons ephemeris: it is not a body but a stream of
debris the Earth ploughs through, seen as meteors diverging from a fixed
radiant on the celestial sphere. What the observer needs to know is therefore
different from a normal target -- where the radiant sits, how high it is, and
how close the date is to the stream's peak.

Peaks are catalogued by solar longitude rather than calendar date. Solar
longitude fixes the Earth's position in its orbit, so a stream crossing always
happens at the same value, whereas the calendar date drifts by up to a day
across the leap-year cycle.

Rates use the standard double-exponential activity profile

    ZHR(lambda) = sum_i zhr_i * 10 ** (-b_i * |lambda - lambda_peak|)

with separate ascending/descending slopes. The tabulated ZHR, slope, and
population index values are approximate literature figures (IMO working list
and Jenniskens' profiles); they describe a typical return, not a prediction
for any particular year.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from astronomy.celestial import solar_longitude_j2000_deg

# Mean apparent motion of the Sun in ecliptic longitude.
_DEG_PER_DAY = 0.9856474


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


@dataclass(frozen=True)
class ActivityComponent:
    """One exponential component of a shower's activity profile."""

    zhr: float
    slope_before: float
    slope_after: float


@dataclass(frozen=True)
class MeteorShower:
    """Radiant geometry and activity profile for one shower."""

    code: str
    name: str
    peak_solar_longitude_deg: float
    radiant_ra_deg: float
    radiant_dec_deg: float
    drift_ra_deg_per_day: float
    drift_dec_deg_per_day: float
    velocity_kms: float
    population_index: float
    components: tuple[ActivityComponent, ...]
    active_before_deg: float
    active_after_deg: float
    parent_body: str

    @property
    def peak_zhr(self) -> float:
        return sum(component.zhr for component in self.components)

    def solar_longitude_offset_deg(self, moment: datetime) -> float:
        """
        Signed distance from the peak in solar longitude.

        Negative before the peak, positive after, wrapped to [-180, 180).
        """
        current = solar_longitude_j2000_deg(moment)
        return ((current - self.peak_solar_longitude_deg + 180.0) % 360.0) - 180.0

    def _refine_peak(self, estimate: datetime) -> datetime:
        """Newton-refine an estimate onto the exact peak solar longitude."""
        for _ in range(12):
            offset = self.solar_longitude_offset_deg(estimate)
            if abs(offset) < 1e-9:
                break
            estimate -= timedelta(days=offset / _DEG_PER_DAY)
        return estimate

    def peak_near(self, moment: datetime) -> datetime:
        """UTC datetime of the peak closest to ``moment``, past or future."""
        moment = _as_utc(moment)
        offset = self.solar_longitude_offset_deg(moment)
        return self._refine_peak(moment - timedelta(days=offset / _DEG_PER_DAY))

    def days_from_peak(self, moment: datetime) -> float:
        """
        Signed days from the peak: negative before, positive after.

        Measured as real elapsed time rather than by dividing the solar
        longitude offset by the Sun's mean daily motion. The Sun runs up to
        1.7% off that mean depending on where Earth is in its orbit, which is
        enough to misreport the distance from a peak by a couple of hours.
        """
        return (_as_utc(moment) - self.peak_near(moment)).total_seconds() / 86400.0

    def is_active(self, moment: datetime) -> bool:
        offset = self.solar_longitude_offset_deg(moment)
        if offset < 0.0:
            return -offset <= self.active_before_deg
        return offset <= self.active_after_deg

    def radiant_at(self, moment: datetime) -> tuple[float, float]:
        """
        Radiant position on a given date, including nightly drift.

        The radiant creeps eastward as the Earth moves through the stream; over
        the Perseids' five-week activity period that amounts to more than 30
        degrees, so the drift is not a refinement that can be skipped.
        """
        days = self.days_from_peak(moment)
        ra = (self.radiant_ra_deg + self.drift_ra_deg_per_day * days) % 360.0
        dec = self.radiant_dec_deg + self.drift_dec_deg_per_day * days
        return ra, max(-90.0, min(90.0, dec))

    def zhr_at(self, moment: datetime) -> float:
        """Zenithal hourly rate for the date, from the activity profile."""
        if not self.is_active(moment):
            return 0.0
        offset = self.solar_longitude_offset_deg(moment)
        total = 0.0
        for component in self.components:
            slope = (
                component.slope_after if offset >= 0.0 else component.slope_before
            )
            total += component.zhr * 10.0 ** (-slope * abs(offset))
        return total

    def next_peak(self, moment: datetime) -> datetime:
        """UTC datetime of the next peak at or after ``moment``."""
        moment = _as_utc(moment)
        current = solar_longitude_j2000_deg(moment)
        ahead = (self.peak_solar_longitude_deg - current) % 360.0
        return self._refine_peak(moment + timedelta(days=ahead / _DEG_PER_DAY))


# Radiant/activity figures are approximate; see the module docstring.
SHOWERS: tuple[MeteorShower, ...] = (
    MeteorShower(
        code="QUA",
        name="Quadrantids",
        peak_solar_longitude_deg=283.15,
        radiant_ra_deg=230.1,
        radiant_dec_deg=49.5,
        drift_ra_deg_per_day=0.40,
        drift_dec_deg_per_day=-0.20,
        velocity_kms=41.0,
        population_index=2.1,
        components=(ActivityComponent(110.0, 2.20, 2.20),),
        active_before_deg=7.0,
        active_after_deg=19.0,
        parent_body="196256 (2003 EH1)",
    ),
    MeteorShower(
        code="LYR",
        name="Lyrids",
        peak_solar_longitude_deg=32.32,
        radiant_ra_deg=271.4,
        radiant_dec_deg=33.6,
        drift_ra_deg_per_day=1.10,
        drift_dec_deg_per_day=0.00,
        velocity_kms=49.0,
        population_index=2.1,
        components=(ActivityComponent(18.0, 0.22, 0.90),),
        active_before_deg=6.5,
        active_after_deg=3.0,
        parent_body="C/1861 G1 (Thatcher)",
    ),
    MeteorShower(
        code="ETA",
        name="eta Aquariids",
        peak_solar_longitude_deg=45.5,
        radiant_ra_deg=338.0,
        radiant_dec_deg=-1.0,
        drift_ra_deg_per_day=0.90,
        drift_dec_deg_per_day=0.40,
        velocity_kms=66.0,
        population_index=2.4,
        components=(ActivityComponent(50.0, 0.08, 0.08),),
        active_before_deg=16.0,
        active_after_deg=22.0,
        parent_body="1P/Halley",
    ),
    MeteorShower(
        code="SDA",
        name="Southern delta Aquariids",
        peak_solar_longitude_deg=125.0,
        radiant_ra_deg=340.0,
        radiant_dec_deg=-16.0,
        drift_ra_deg_per_day=0.80,
        drift_dec_deg_per_day=0.20,
        velocity_kms=41.0,
        population_index=3.2,
        components=(ActivityComponent(25.0, 0.09, 0.09),),
        active_before_deg=16.0,
        active_after_deg=25.0,
        parent_body="96P/Machholz",
    ),
    MeteorShower(
        code="PER",
        name="Perseids",
        peak_solar_longitude_deg=140.0,
        radiant_ra_deg=48.2,
        radiant_dec_deg=58.1,
        drift_ra_deg_per_day=1.40,
        drift_dec_deg_per_day=0.25,
        velocity_kms=59.0,
        population_index=2.2,
        # Broad background plus a narrow maximum, after Jenniskens (1994).
        components=(
            ActivityComponent(20.0, 0.05, 0.05),
            ActivityComponent(80.0, 0.35, 0.40),
        ),
        active_before_deg=26.0,
        active_after_deg=11.0,
        parent_body="109P/Swift-Tuttle",
    ),
    MeteorShower(
        code="DRA",
        name="Draconids",
        peak_solar_longitude_deg=195.4,
        radiant_ra_deg=262.0,
        radiant_dec_deg=55.7,
        drift_ra_deg_per_day=0.00,
        drift_dec_deg_per_day=0.00,
        velocity_kms=20.0,
        population_index=2.6,
        # Highly variable: quiet in most years, storms in a few.
        components=(ActivityComponent(5.0, 2.50, 2.50),),
        active_before_deg=1.0,
        active_after_deg=1.5,
        parent_body="21P/Giacobini-Zinner",
    ),
    MeteorShower(
        code="ORI",
        name="Orionids",
        peak_solar_longitude_deg=208.0,
        radiant_ra_deg=95.0,
        radiant_dec_deg=16.0,
        drift_ra_deg_per_day=1.23,
        drift_dec_deg_per_day=0.13,
        velocity_kms=66.0,
        population_index=2.5,
        components=(ActivityComponent(20.0, 0.12, 0.12),),
        active_before_deg=20.0,
        active_after_deg=11.0,
        parent_body="1P/Halley",
    ),
    MeteorShower(
        code="LEO",
        name="Leonids",
        peak_solar_longitude_deg=235.27,
        radiant_ra_deg=152.0,
        radiant_dec_deg=22.0,
        drift_ra_deg_per_day=1.39,
        drift_dec_deg_per_day=-0.44,
        velocity_kms=71.0,
        population_index=2.5,
        components=(ActivityComponent(15.0, 0.55, 0.55),),
        active_before_deg=12.0,
        active_after_deg=13.0,
        parent_body="55P/Tempel-Tuttle",
    ),
    MeteorShower(
        code="GEM",
        name="Geminids",
        peak_solar_longitude_deg=262.2,
        radiant_ra_deg=112.0,
        radiant_dec_deg=32.5,
        drift_ra_deg_per_day=1.02,
        drift_dec_deg_per_day=-0.15,
        velocity_kms=35.0,
        population_index=2.6,
        components=(ActivityComponent(150.0, 0.39, 0.39),),
        active_before_deg=11.0,
        active_after_deg=3.5,
        parent_body="3200 Phaethon",
    ),
    MeteorShower(
        code="URS",
        name="Ursids",
        peak_solar_longitude_deg=270.7,
        radiant_ra_deg=217.0,
        radiant_dec_deg=75.5,
        drift_ra_deg_per_day=0.50,
        drift_dec_deg_per_day=-0.10,
        velocity_kms=33.0,
        population_index=3.0,
        components=(ActivityComponent(10.0, 0.90, 0.90),),
        active_before_deg=1.5,
        active_after_deg=3.5,
        parent_body="8P/Tuttle",
    ),
)


_BY_CODE = {shower.code: shower for shower in SHOWERS}
_BY_NAME = {shower.name.lower(): shower for shower in SHOWERS}


class UnknownShowerError(ValueError):
    """Raised when a target command does not name a known shower."""


def get_shower(identifier: str) -> MeteorShower:
    """Look up a shower by IAU code or by name."""
    token = identifier.strip().strip("'\"")
    shower = _BY_CODE.get(token.upper()) or _BY_NAME.get(token.lower())
    if shower is None:
        known = ", ".join(sorted(_BY_CODE))
        raise UnknownShowerError(f"Unknown meteor shower {identifier!r}. Known: {known}")
    return shower


def shower_target_command(shower: MeteorShower) -> str:
    """Target command string identifying a shower to the meteor fetcher."""
    return f"SHOWER={shower.code}"


def parse_target_command(target_command: str) -> MeteorShower:
    """
    Resolve a ``SHOWER=<code>`` target command.

    Bare codes and names are accepted too, so ``SHOWER=PER``, ``PER`` and
    ``Perseids`` all work.
    """
    token = target_command.strip().strip("'\"")
    if "=" in token:
        prefix, _, value = token.partition("=")
        if prefix.strip().upper() != "SHOWER":
            raise UnknownShowerError(
                f"Not a meteor shower target command: {target_command!r}"
            )
        token = value.strip().rstrip(";")
    return get_shower(token)


def observed_hourly_rate(
    zhr: float,
    radiant_altitude_deg: float,
    limiting_magnitude: float,
    population_index: float,
    obstructed_sky_fraction: float = 0.0,
) -> float:
    """
    Convert a zenithal hourly rate into the rate a real observer would count.

    This is the standard IMO relation inverted: ZHR is defined for a radiant at
    the zenith under a 6.5-magnitude sky with nothing blocking the view, so a
    real session is scaled down by radiant altitude, by how much fainter the
    actual limiting magnitude is, and by any obstructed fraction of sky.
    """
    if radiant_altitude_deg <= 0.0 or zhr <= 0.0:
        return 0.0
    altitude_factor = math.sin(math.radians(radiant_altitude_deg))
    magnitude_factor = population_index ** (6.5 - limiting_magnitude)
    clear_fraction = max(0.0, 1.0 - obstructed_sky_fraction)
    return zhr * altitude_factor * clear_fraction / magnitude_factor
