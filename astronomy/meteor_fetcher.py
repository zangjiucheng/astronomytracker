"""
meteor_fetcher.py

Ephemeris provider for meteor shower radiants.

Drop-in replacement for ``HorizonsFetcher`` that computes radiant positions
locally instead of querying JPL Horizons, which has no ephemeris for a meteor
shower. Because the arithmetic is local it also runs offline and returns a
24-hour forecast instantly rather than over a network round trip.

IP geolocation and weather are still real network calls and are delegated to
``HorizonsFetcher`` so the two providers stay interchangeable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from astronomy import celestial
from astronomy.api_fetcher import HorizonsFetcher
from astronomy.meteor_showers import MeteorShower, parse_target_command
from astronomy.tracker_state import (
    EphemerisSample,
    ObserverLocation,
    compass_from_azimuth,
)

# Meteors ablate in the mesosphere, so this is the distance the observer is
# actually looking at -- unlike a Horizons target there is no body to range to.
ABLATION_ALTITUDE_KM = 100.0
_KM_PER_AU = 149597870.7


class MeteorRadiantFetcher:
    """Computes radiant ephemeris samples for a meteor shower."""

    # Radiant samples are local arithmetic rather than network rows -- a few
    # thousand take a fraction of a second -- so a shower forecast can keep a
    # fine step over a horizon of weeks.
    MAX_RANGE_SAMPLES = 4500

    def __init__(self, timeout_sec: int = 30, retries: int = 3) -> None:
        # Accepted for signature compatibility with HorizonsFetcher; only the
        # delegated network calls use them.
        self.timeout_sec = timeout_sec
        self.retries = retries
        self._network_fetcher: HorizonsFetcher | None = None

    def _delegate(self) -> HorizonsFetcher:
        if self._network_fetcher is None:
            self._network_fetcher = HorizonsFetcher(
                timeout_sec=self.timeout_sec, retries=self.retries
            )
        return self._network_fetcher

    def build_sample(
        self,
        shower: MeteorShower,
        location: ObserverLocation,
        observation_time: datetime,
    ) -> EphemerisSample:
        """Compute one radiant sample for a shower at a moment in time."""
        if observation_time.tzinfo is None:
            observation_time = observation_time.replace(tzinfo=timezone.utc)
        utc_time = observation_time.astimezone(timezone.utc)

        ra_deg, dec_deg = shower.radiant_at(utc_time)
        altitude_deg, azimuth_deg = celestial.equatorial_to_horizontal(
            ra_deg,
            dec_deg,
            location.latitude_deg,
            location.longitude_deg,
            utc_time,
        )

        sky = celestial.sky_context(
            location.latitude_deg, location.longitude_deg, utc_time
        )
        solar_elongation = celestial.angular_separation_deg(
            ra_deg, dec_deg, sky.sun_ra_deg, sky.sun_dec_deg
        )
        moon_separation = celestial.angular_separation_deg(
            ra_deg, dec_deg, sky.moon_ra_deg, sky.moon_dec_deg
        )

        return EphemerisSample(
            utc_time=utc_time,
            local_time=utc_time.astimezone(),
            ra_deg=ra_deg,
            dec_deg=dec_deg,
            az_deg=azimuth_deg,
            el_deg=altitude_deg,
            solar_elong_deg=solar_elongation,
            compass_direction=compass_from_azimuth(azimuth_deg),
            visibility_status=(
                "Radiant above horizon"
                if altitude_deg > 0.0
                else "Radiant below horizon"
            ),
            range_au=ABLATION_ALTITUDE_KM / _KM_PER_AU,
            # Horizons reports approach as a negative range rate; meteors are
            # always closing at the stream's geocentric velocity.
            range_rate_kms=-shower.velocity_kms,
            solar_presence=celestial.solar_presence_code(sky.sun_altitude_deg),
            interferer_presence="m" if sky.moon_altitude_deg > 0.0 else "",
            solar_alignment_code="",
            sun_alt_deg=sky.sun_altitude_deg,
            moon_alt_deg=sky.moon_altitude_deg,
            moon_illumination=sky.moon_illumination,
            moon_separation_deg=moon_separation,
        )

    def fetch_current_ephemeris(
        self,
        target_command: str,
        location: ObserverLocation,
        observation_time: datetime | None = None,
    ) -> EphemerisSample:
        shower = parse_target_command(target_command)
        if observation_time is None:
            observation_time = datetime.now(timezone.utc)
        return self.build_sample(shower, location, observation_time)

    def fetch_ephemeris_range(
        self,
        target_command: str,
        location: ObserverLocation,
        start_time: datetime,
        stop_time: datetime,
        step_minutes: int = 1,
    ) -> list[EphemerisSample]:
        shower = parse_target_command(target_command)
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if stop_time.tzinfo is None:
            stop_time = stop_time.replace(tzinfo=timezone.utc)

        step = timedelta(minutes=max(1, int(step_minutes)))
        samples: list[EphemerisSample] = []
        moment = start_time
        while moment <= stop_time:
            samples.append(self.build_sample(shower, location, moment))
            moment += step
        return samples

    def fetch_ip_location(self) -> tuple[ObserverLocation, str]:
        return self._delegate().fetch_ip_location()

    def fetch_open_meteo_weather(
        self, location: ObserverLocation
    ) -> tuple[dict[str, float | None], dict[datetime, dict[str, float | None]]]:
        return self._delegate().fetch_open_meteo_weather(location)
