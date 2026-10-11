from __future__ import annotations

from copy import deepcopy

import pytest

from coordinator.decision_manager import DecisionManager
from coordinator.errors import CoordinatorError, ErrorCode
from coordinator.event_manager import EventManager
from tests.helpers import valid_analysis


@pytest.fixture
def handoff(sandbox_project):
    manager = EventManager(sandbox_project / "schemas" / "event_handoff.schema.json")
    return manager.build_handoff(manager.load_event(sandbox_project / "samples" / "simulated_event.json"))


@pytest.fixture
def decision_manager(sandbox_project):
    return DecisionManager(sandbox_project / "schemas" / "decision.schema.json")


def test_t08_decision_schema_passes(decision_manager, handoff):
    decision = decision_manager.build_decision(valid_analysis(handoff), handoff=handoff, provider="openai", model="mock-model")
    decision_manager.validate_decision(decision, handoff)
    assert decision["action"] == "WATCH"


def test_t09_handoff_id_mismatch_fails(decision_manager, handoff):
    decision = decision_manager.build_decision(valid_analysis(handoff), handoff=handoff, provider="openai", model="mock-model")
    decision["handoff_id"] = "WRONG-HANDOFF"
    with pytest.raises(CoordinatorError) as caught:
        decision_manager.validate_decision(decision, handoff)
    assert caught.value.code == ErrorCode.SCHEMA_VALIDATION_FAILED


def test_t10_tracking_session_id_mismatch_fails(decision_manager, handoff):
    decision = decision_manager.build_decision(valid_analysis(handoff), handoff=handoff, provider="openai", model="mock-model")
    decision["tracking_session_id"] = "WRONG-SESSION"
    with pytest.raises(CoordinatorError) as caught:
        decision_manager.validate_decision(decision, handoff)
    assert caught.value.code == ErrorCode.SCHEMA_VALIDATION_FAILED


def test_t11_illegal_action_fails(decision_manager, handoff):
    analysis = valid_analysis(handoff)
    analysis["action"] = "BUY"
    with pytest.raises(CoordinatorError) as caught:
        decision_manager.build_decision(analysis, handoff=handoff, provider="openai", model="mock-model")
    assert caught.value.code == ErrorCode.SCHEMA_VALIDATION_FAILED


def test_model_cursor_is_ignored_in_favor_of_frozen_snapshot(decision_manager, handoff):
    analysis = valid_analysis(handoff)
    analysis["processed_through_seq"] = handoff["cursor_snapshot"]["handoff_max_event_seq"] + 1
    decision = decision_manager.build_decision(analysis, handoff=handoff, provider="openai", model="mock-model")
    assert decision["processed_through_seq"] == handoff["cursor_snapshot"]["handoff_max_event_seq"]


def test_model_cannot_spoof_trusted_metadata(decision_manager, handoff):
    analysis = valid_analysis(handoff)
    analysis.update({"handoff_id": "SPOOF", "tracking_session_id": "SPOOF", "provider": "spoof"})
    decision = decision_manager.build_decision(analysis, handoff=handoff, provider="openai", model="mock-model")
    assert decision["handoff_id"] == handoff["handoff_id"]
    assert decision["tracking_session_id"] == handoff["tracking_session_id"]
    assert decision["provider"] == "openai"


def test_provider_schema_uses_structured_output_compatible_subset(decision_manager):
    schema_text = str(decision_manager.provider_output_schema())
    for unsupported in ("minLength", "maxLength", "minimum", "maximum", "pattern", "minItems", "maxItems"):
        assert unsupported not in schema_text
    assert "additionalProperties" in schema_text
    assert "action" in schema_text
