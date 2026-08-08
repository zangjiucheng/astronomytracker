from astronomy.gui import TrackerAppConfig, run_app
from astronomy.meteor_fetcher import MeteorRadiantFetcher
from astronomy.meteor_showers import get_shower, shower_target_command
from astronomy.tracker_state import ObserverLocation, TrackerState


PERSEIDS = get_shower("PER")

APP_CONFIG = TrackerAppConfig(
    app_name="Perseids Tracker",
    organization_name="Astronomy",
    window_title="Perseids Astronomy Tracker",
    header_title="Perseid Meteor Shower Real-Time Tracker",
    header_subtitle=(
        "PySide6 desktop tracker following the Perseid radiant, with estimated "
        "meteor rate, moonlight interference, and a 24-hour forecast."
    ),
    target_name=PERSEIDS.name,
    scorer_target_type="meteor_shower_per",
    # The radiant has no Horizons ephemeris; it is computed locally.
    fetcher_factory=MeteorRadiantFetcher,
    auto_ip_location=True,
    # A week ahead by default so the maximum is in view before it arrives.
    # Radiant samples are computed locally, so this stays at 5-minute steps.
    prediction_horizon_minutes=7 * 24 * 60,
)

INITIAL_STATE = TrackerState(
    # Overwritten by the IP lookup on startup; kept as a fallback for when the
    # geolocation service is unreachable.
    target_command=shower_target_command(PERSEIDS),
    location=ObserverLocation(43.2557, -79.8711, 0.10),
    refresh_interval_sec=10,
)


if __name__ == "__main__":
    raise SystemExit(run_app(state=INITIAL_STATE, config=APP_CONFIG))
