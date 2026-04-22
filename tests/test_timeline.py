from __future__ import annotations

from astronomy.timeline import select_timeline_sample


def test_select_timeline_live_sample() -> None:
    selection = select_timeline_sample(
        latest_sample="live",
        history_samples=["h0", "h1"],
        predicted_samples=["p0", "p1"],
        history_step_minutes=5,
        prediction_step_minutes=5,
        offset_minutes=0,
    )

    assert selection.kind == "live"
    assert selection.sample == "live"
    assert selection.preview is False


def test_select_timeline_history_uses_history_not_prediction() -> None:
    selection = select_timeline_sample(
        latest_sample="live",
        history_samples=["h0", "h1", "h2"],
        predicted_samples=["p0", "p1", "p2"],
        history_step_minutes=5,
        prediction_step_minutes=5,
        offset_minutes=-5,
    )

    assert selection.kind == "history"
    assert selection.sample == "h1"
    assert selection.preview is True


def test_select_timeline_history_falls_back_to_live_without_history() -> None:
    selection = select_timeline_sample(
        latest_sample="live",
        history_samples=[],
        predicted_samples=["p0", "p1"],
        history_step_minutes=5,
        prediction_step_minutes=5,
        offset_minutes=-5,
    )

    assert selection.kind == "live"
    assert selection.sample == "live"
    assert selection.preview is True


def test_select_timeline_prediction_sample() -> None:
    selection = select_timeline_sample(
        latest_sample="live",
        history_samples=["h0", "h1"],
        predicted_samples=["p0", "p1", "p2"],
        history_step_minutes=5,
        prediction_step_minutes=5,
        offset_minutes=5,
    )

    assert selection.kind == "prediction"
    assert selection.sample == "p1"
    assert selection.preview is True


def test_select_timeline_clamps_out_of_range_offsets() -> None:
    history_selection = select_timeline_sample(
        latest_sample="live",
        history_samples=["h0", "h1"],
        predicted_samples=[],
        history_step_minutes=5,
        prediction_step_minutes=5,
        offset_minutes=-500,
    )
    prediction_selection = select_timeline_sample(
        latest_sample="live",
        history_samples=[],
        predicted_samples=["p0", "p1"],
        history_step_minutes=5,
        prediction_step_minutes=5,
        offset_minutes=500,
    )

    assert history_selection.sample == "h0"
    assert prediction_selection.sample == "p1"
