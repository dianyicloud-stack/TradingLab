from __future__ import annotations

from coordinator.event_manager import EventManager


def test_t05_simulated_event_builds_full_handoff(sandbox_project):
    manager = EventManager(sandbox_project / "schemas" / "event_handoff.schema.json")
    event_input = manager.load_event(sandbox_project / "samples" / "simulated_event.json")
    handoff = manager.build_handoff(event_input)
    assert handoff["handoff_type"] == "EVENT_INTERRUPT"
    assert handoff["trigger_event"]["severity"] == "IMPORTANT"
    assert len(handoff["observation_rows_since_checkpoint"]) == 2
    assert [event["event_seq"] for event in handoff["events_since_checkpoint"]] == [16, 17]
    assert handoff["runtime_context"]["window_seconds"] == 120
    assert handoff["decision_checkpoint"]


def test_t06_event_handoff_schema_passes(sandbox_project):
    manager = EventManager(sandbox_project / "schemas" / "event_handoff.schema.json")
    handoff = manager.build_handoff(manager.load_event(sandbox_project / "samples" / "simulated_event.json"))
    manager.validate_handoff(handoff)
    assert handoff["cursor_snapshot"]["handoff_max_event_seq"] == 17
