import numpy as np
import pytest
from pydantic import ValidationError

from ygo_assistant.bootstrap import load_config
from ygo_assistant.capture.base import Frame
from ygo_assistant.events.schemas import DuelEvent, Evidence
from ygo_assistant.state.schemas import DuelState


def test_frame_contract():
    image = np.zeros((4, 8, 3), dtype=np.uint8)
    assert Frame(0, 10, image, "video_file", 8, 4).timestamp_ms == 10
    with pytest.raises(ValueError):
        Frame(0, 10, image, "video_file", 4, 8)
    with pytest.raises(ValueError):
        Frame(0, -1, image, "live_window", 8, 4)


def test_unknown_state_and_independent_defaults():
    first = DuelState(match_id="match_1")
    second = DuelState(match_id="match_2")
    assert first.players["PLAYER_B"].life_points is None
    assert first.legal_actions is None
    assert first.unknown_card_counts["PLAYER_B"] is None
    first.unresolved_events.append("event_1")
    assert second.unresolved_events == []
    assert DuelState.model_validate_json(first.model_dump_json()) == first


def test_event_evidence_round_trip():
    event = DuelEvent(
        match_id="m", event_id="e", timestamp_ms=120,
        evidence=[Evidence(source="duel_log", timestamp_ms=120, roi="R1",
                           frame_id=3, raw_text="发动效果", confidence=0.7)],
    )
    assert DuelEvent.model_validate_json(event.model_dump_json()) == event
    assert event.status == "unresolved"
    assert event.state_version_before is None


@pytest.mark.parametrize("changes", [
    {"confidence": 1.1}, {"timestamp_ms": -1}, {"actor": "guess"},
    {"state_version_before": 0},
    {"state_version_before": 1, "state_version_after": 3},
    {"state_version_before": 0, "state_version_after": 1, "status": "rejected"},
    {"schema_version": "2.0"}, {"unexpected": True},
])
def test_invalid_events(changes):
    values = dict(match_id="m", event_id="e", timestamp_ms=0)
    values.update(changes)
    with pytest.raises(ValidationError):
        DuelEvent(**values)


def test_consecutive_versions():
    event = DuelEvent(match_id="m", event_id="e", timestamp_ms=0,
                      state_version_before=4, state_version_after=5)
    assert event.state_version_after == 5


def test_configuration_paths(tmp_path):
    path = tmp_path / "app.yaml"
    path.write_text("mode: live\nlog_directory: output\n", encoding="utf-8")
    config = load_config(path)
    assert config.mode == "live"
    assert config.log_directory == tmp_path / "output"
    assert load_config().frame_queue_size == 2


@pytest.mark.parametrize("content", ["[]", "", "capture_fps: 0", "typo: 1"])
def test_invalid_configuration(tmp_path, content):
    path = tmp_path / "app.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)
