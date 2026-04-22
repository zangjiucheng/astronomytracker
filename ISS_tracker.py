from astronomy.gui import TrackerAppConfig, run_app
from astronomy.tracker_state import ObserverLocation, TrackerState


APP_CONFIG = TrackerAppConfig(
    app_name="ISS Tracker",
    organization_name="Astronomy",
    window_title="ISS Astronomy Tracker",
    header_title="International Space Station Real-Time Tracker",
    header_subtitle="PySide6 desktop tracker with live JPL Horizons sampling, historical log, and azimuth/elevation plot.",
    target_name="International Space Station",
    scorer_target_type="satellite",
)

INITIAL_STATE = TrackerState(
    target_command="-125544",
    location=ObserverLocation(43.2557, -79.8711, 0.10),
    refresh_interval_sec=10,
)


if __name__ == "__main__":
    raise SystemExit(run_app(state=INITIAL_STATE, config=APP_CONFIG))
