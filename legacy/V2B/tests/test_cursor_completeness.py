from __future__ import annotations

from copy import deepcopy

import pytest

from coordinator.decision_manager import DecisionManager
from coordinator.errors import CoordinatorError, ErrorCode
from coordinator.event_manager import EventManager
from tests.helpers import valid_analysis


def manager(project):
    return EventManager(project / "schemas" / "event_handoff.schema.json")


def standard_handoff(project):
    event_manager = manager(project)
    return event_manager.build_handoff(
        event_manager.load_event(project / "samples" / "simulated_event.json")
    )


def three_event_handoff(project):
    handoff = standard_handoff(project)
    event_18 = deepcopy(handoff["trigger_event"])
    event_18.update({
        "event_id": "E-20260901-TS-20260901-bj920161-01-0018",
        "event_seq": 18,
        "timestamp": "2026-09-01T10:16:00+08:00",
    })
    handoff["events_since_checkpoint"].append(deepcopy(event_18))
    handoff["trigger_event"] = deepcopy(event_18)
    handoff["cursor_snapshot"]["handoff_max_event_seq"] = 18
    for field in ("source_event_ids", "member_event_ids"):
        handoff["composite_event"][field].append(event_18["event_id"])
    return handoff


def assert_semantic_failure(project, handoff):
    with pytest.raises(CoordinatorError) as caught:
        manager(project).validate_handoff(handoff)
    assert caught.value.code == ErrorCode.HANDOFF_SEMANTIC_VALIDATION_FAILED


def test_t45_empty_rows_with_equal_observation_cursors_pass(sandbox_project):
    event_manager = manager(sandbox_project)
    handoff = event_manager.build_handoff(
        event_manager.load_event(sandbox_project / "samples" / "simulated_event_no_observation.json")
    )
    assert handoff["observation_rows_since_checkpoint"] == []
    assert handoff["cursor_snapshot"]["last_processed_observation_time"] == "10:20"
    assert handoff["cursor_snapshot"]["handoff_max_observation_time"] == "10:20"
    assert handoff["runtime_context"]["samples"][-1]["timestamp"].endswith("10:21:15+08:00")


def test_t46_empty_rows_with_advanced_observation_max_fail(sandbox_project):
    handoff = standard_handoff(sandbox_project)
    handoff["observation_rows_since_checkpoint"] = []
    assert_semantic_failure(sandbox_project, handoff)


def test_t47_rows_must_be_later_than_last_processed_observation(sandbox_project):
    handoff = standard_handoff(sandbox_project)
    handoff["observation_rows_since_checkpoint"].insert(0, {"requested_time": "10:05"})
    assert_semantic_failure(sandbox_project, handoff)


def test_t48_strict_incremental_observations_with_exact_max_pass(sandbox_project):
    handoff = standard_handoff(sandbox_project)
    manager(sandbox_project).validate_handoff(handoff)
    assert [row["requested_time"] for row in handoff["observation_rows_since_checkpoint"]] == ["10:10", "10:15"]
    assert handoff["cursor_snapshot"]["handoff_max_observation_time"] == "10:15"


def test_t49_observation_max_must_equal_latest_included_row(sandbox_project):
    handoff = standard_handoff(sandbox_project)
    handoff["cursor_snapshot"]["handoff_max_observation_time"] = "10:20"
    assert_semantic_failure(sandbox_project, handoff)


def test_t50_observation_requested_time_must_be_unique(sandbox_project):
    handoff = standard_handoff(sandbox_project)
    handoff["observation_rows_since_checkpoint"][1]["requested_time"] = "10:10"
    handoff["cursor_snapshot"]["handoff_max_observation_time"] = "10:10"
    assert_semantic_failure(sandbox_project, handoff)


def test_t51_observation_requested_time_must_be_ascending(sandbox_project):
    handoff = standard_handoff(sandbox_project)
    handoff["observation_rows_since_checkpoint"].reverse()
    assert_semantic_failure(sandbox_project, handoff)


def test_t52_contiguous_event_increment_passes(sandbox_project):
    handoff = three_event_handoff(sandbox_project)
    manager(sandbox_project).validate_handoff(handoff)
    assert [event["event_seq"] for event in handoff["events_since_checkpoint"]] == [16, 17, 18]


def test_t53_event_increment_with_middle_gap_fails(sandbox_project):
    handoff = three_event_handoff(sandbox_project)
    handoff["events_since_checkpoint"] = [handoff["events_since_checkpoint"][0], handoff["events_since_checkpoint"][2]]
    assert_semantic_failure(sandbox_project, handoff)


def test_t54_event_increment_missing_first_seq_fails(sandbox_project):
    handoff = three_event_handoff(sandbox_project)
    handoff["events_since_checkpoint"] = handoff["events_since_checkpoint"][1:]
    assert_semantic_failure(sandbox_project, handoff)


def test_t55_event_seq_must_be_unique(sandbox_project):
    handoff = three_event_handoff(sandbox_project)
    handoff["events_since_checkpoint"].insert(2, deepcopy(handoff["events_since_checkpoint"][1]))
    assert_semantic_failure(sandbox_project, handoff)


def test_t56_event_seq_must_be_ascending(sandbox_project):
    handoff = three_event_handoff(sandbox_project)
    handoff["events_since_checkpoint"].reverse()
    assert_semantic_failure(sandbox_project, handoff)


def test_t57_empty_event_increment_with_equal_event_cursors_passes(sandbox_project):
    handoff = standard_handoff(sandbox_project)
    handoff["events_since_checkpoint"] = []
    handoff["cursor_snapshot"]["handoff_max_event_seq"] = 15
    handoff["trigger_event"]["event_seq"] = 15
    handoff["composite_event"] = None
    manager(sandbox_project).validate_handoff(handoff)


def test_t58_empty_event_increment_with_advanced_event_max_fails(sandbox_project):
    handoff = standard_handoff(sandbox_project)
    handoff["events_since_checkpoint"] = []
    handoff["cursor_snapshot"]["handoff_max_event_seq"] = 16
    handoff["trigger_event"]["event_seq"] = 16
    handoff["composite_event"] = None
    assert_semantic_failure(sandbox_project, handoff)


def test_t59_trigger_event_in_complete_increment_passes(sandbox_project):
    handoff = three_event_handoff(sandbox_project)
    manager(sandbox_project).validate_handoff(handoff)
    assert handoff["trigger_event"]["event_seq"] in {
        event["event_seq"] for event in handoff["events_since_checkpoint"]
    }


def test_t60_trigger_event_absent_from_increment_fails(sandbox_project):
    handoff = three_event_handoff(sandbox_project)
    handoff["events_since_checkpoint"] = handoff["events_since_checkpoint"][:2]
    handoff["composite_event"] = None
    assert_semantic_failure(sandbox_project, handoff)


def test_t61_composite_source_event_must_be_in_increment(sandbox_project):
    handoff = three_event_handoff(sandbox_project)
    handoff["composite_event"]["source_event_ids"].append("E-MISSING")
    assert_semantic_failure(sandbox_project, handoff)


def test_t62_final_decision_event_cursor_equals_frozen_max(sandbox_project):
    handoff = three_event_handoff(sandbox_project)
    analysis = valid_analysis(handoff)
    analysis["processed_through_seq"] = 999
    decision = DecisionManager(sandbox_project / "schemas" / "decision.schema.json").build_decision(
        analysis,
        handoff=handoff,
        provider="openai",
        model="mock-model",
    )
    assert decision["processed_through_seq"] == 18


def test_t63_final_decision_observation_cursor_equals_frozen_max(sandbox_project):
    handoff = standard_handoff(sandbox_project)
    analysis = valid_analysis(handoff)
    analysis["processed_through_observation_time"] = "23:59"
    decision = DecisionManager(sandbox_project / "schemas" / "decision.schema.json").build_decision(
        analysis,
        handoff=handoff,
        provider="openai",
        model="mock-model",
    )
    assert decision["processed_through_observation_time"] == "10:15"
