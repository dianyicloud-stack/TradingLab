from __future__ import annotations

from copy import deepcopy

import pytest

from coordinator.decision_manager import DecisionManager
from coordinator.errors import CoordinatorError, ErrorCode
from coordinator.event_manager import EventManager
from coordinator.job_manager import JobManager
from coordinator.service import V2BCoordinator
from coordinator.usage_manager import UsageManager
from providers import build_provider
from tests.helpers import FakeProvider, fake_factory, valid_analysis


def make_manager(project):
    return EventManager(project / "schemas" / "event_handoff.schema.json")


def make_handoff(project):
    manager = make_manager(project)
    return manager.build_handoff(manager.load_event(project / "samples" / "simulated_event.json"))


def make_service(project, provider=None):
    provider = provider or FakeProvider()
    return V2BCoordinator(
        project,
        provider_factory=fake_factory(provider),
        sleep_fn=lambda _seconds: None,
    )


def assert_semantic_failure(manager, handoff):
    with pytest.raises(CoordinatorError) as caught:
        manager.validate_handoff(handoff)
    assert caught.value.code == ErrorCode.HANDOFF_SEMANTIC_VALIDATION_FAILED


def test_t24_empty_observation_rows_pass_schema(sandbox_project):
    manager = make_manager(sandbox_project)
    event_input = manager.load_event(sandbox_project / "samples" / "simulated_event.json")
    event_input["observation_rows_since_checkpoint"] = []
    event_input["cursor_snapshot"]["handoff_max_observation_time"] = "10:05"
    handoff = manager.build_handoff(event_input)
    assert handoff["observation_rows_since_checkpoint"] == []


def test_t25_empty_observations_with_runtime_context_pass_semantics(sandbox_project):
    manager = make_manager(sandbox_project)
    event_input = manager.load_event(sandbox_project / "samples" / "simulated_event.json")
    event_input["observation_rows_since_checkpoint"] = []
    event_input["cursor_snapshot"]["handoff_max_observation_time"] = "10:05"
    handoff = manager.build_handoff(event_input)
    manager.validate_handoff_semantics(handoff)
    assert handoff["runtime_context"]["samples"]


def test_t26_wrong_model_event_cursor_is_overwritten(sandbox_project):
    handoff = make_handoff(sandbox_project)
    analysis = valid_analysis(handoff)
    analysis["processed_through_seq"] = 999999
    decision = DecisionManager(sandbox_project / "schemas" / "decision.schema.json").build_decision(
        analysis,
        handoff=handoff,
        provider="openai",
        model="mock-model",
    )
    assert decision["processed_through_seq"] == handoff["cursor_snapshot"]["handoff_max_event_seq"]


def test_t27_wrong_model_observation_cursor_is_overwritten(sandbox_project):
    handoff = make_handoff(sandbox_project)
    analysis = valid_analysis(handoff)
    analysis["processed_through_observation_time"] = "23:59"
    decision = DecisionManager(sandbox_project / "schemas" / "decision.schema.json").build_decision(
        analysis,
        handoff=handoff,
        provider="openai",
        model="mock-model",
    )
    assert decision["processed_through_observation_time"] == "10:15"


def test_t28_null_observation_max_produces_null_decision_cursor(sandbox_project):
    handoff = make_handoff(sandbox_project)
    handoff["observation_rows_since_checkpoint"] = []
    handoff["cursor_snapshot"]["last_processed_observation_time"] = None
    handoff["cursor_snapshot"]["handoff_max_observation_time"] = None
    make_manager(sandbox_project).validate_handoff(handoff)
    decision = DecisionManager(sandbox_project / "schemas" / "decision.schema.json").build_decision(
        valid_analysis(handoff),
        handoff=handoff,
        provider="openai",
        model="mock-model",
    )
    assert decision["processed_through_observation_time"] is None


def test_t29_event_cursor_bounds_conflict_fails_before_job_creation(sandbox_project):
    handoff = make_handoff(sandbox_project)
    handoff["cursor_snapshot"]["last_processed_event_seq"] = 18
    service = make_service(sandbox_project)
    with pytest.raises(CoordinatorError) as caught:
        service.analyze_handoff(handoff)
    assert caught.value.code == ErrorCode.HANDOFF_SEMANTIC_VALIDATION_FAILED
    assert (sandbox_project / "state" / "jobs.jsonl").read_text(encoding="utf-8") == ""


def test_t30_observation_cursor_bounds_conflict_fails(sandbox_project):
    handoff = make_handoff(sandbox_project)
    handoff["cursor_snapshot"]["last_processed_observation_time"] = "10:20"
    assert_semantic_failure(make_manager(sandbox_project), handoff)


def test_t31_trigger_event_above_handoff_max_fails(sandbox_project):
    handoff = make_handoff(sandbox_project)
    handoff["cursor_snapshot"]["handoff_max_event_seq"] = 16
    assert_semantic_failure(make_manager(sandbox_project), handoff)


def test_t32_tracking_session_conflict_fails(sandbox_project):
    handoff = make_handoff(sandbox_project)
    handoff["trigger_event"]["tracking_session_id"] = "TS-WRONG"
    assert_semantic_failure(make_manager(sandbox_project), handoff)


def test_t33_observation_later_than_frozen_max_fails(sandbox_project):
    handoff = make_handoff(sandbox_project)
    handoff["observation_rows_since_checkpoint"][-1]["requested_time"] = "10:20"
    assert_semantic_failure(make_manager(sandbox_project), handoff)


def test_t34_enabled_provider_without_registry_adapter_fails():
    with pytest.raises(CoordinatorError) as caught:
        build_provider(
            "minimax",
            {"enabled": True},
            prompt="test",
            output_schema={"type": "object"},
        )
    assert caught.value.code == ErrorCode.PROVIDER_NOT_IMPLEMENTED


def test_t35_registered_but_disabled_provider_fails():
    with pytest.raises(CoordinatorError) as caught:
        build_provider(
            "openai",
            {"enabled": False},
            prompt="test",
            output_schema={"type": "object"},
        )
    assert caught.value.code == ErrorCode.PROVIDER_DISABLED


def test_t36_result_ready_cannot_return_to_running(sandbox_project):
    manager = JobManager(sandbox_project / "state" / "jobs.jsonl")
    job = manager.create(make_handoff(sandbox_project), "openai", "mock-model")
    job = manager.transition(job, "RUNNING", attempt=1)
    job = manager.transition(job, "RESULT_READY", decision_id="DEC-MOCK")
    with pytest.raises(CoordinatorError) as caught:
        manager.transition(job, "RUNNING", attempt=2)
    assert caught.value.code == ErrorCode.JOB_INVALID_TRANSITION


def test_t37_failed_cannot_return_to_running(sandbox_project):
    manager = JobManager(sandbox_project / "state" / "jobs.jsonl")
    job = manager.create(make_handoff(sandbox_project), "openai", "mock-model")
    job = manager.transition(job, "FAILED", error_code="MOCK")
    with pytest.raises(CoordinatorError) as caught:
        manager.transition(job, "RUNNING", attempt=1)
    assert caught.value.code == ErrorCode.JOB_INVALID_TRANSITION


def test_t38_running_to_result_ready_passes(sandbox_project):
    manager = JobManager(sandbox_project / "state" / "jobs.jsonl")
    job = manager.create(make_handoff(sandbox_project), "openai", "mock-model")
    job = manager.transition(job, "RUNNING", attempt=1)
    job = manager.transition(job, "RESULT_READY", decision_id="DEC-MOCK")
    assert job["status"] == "RESULT_READY"


def test_t39_running_to_failed_passes(sandbox_project):
    manager = JobManager(sandbox_project / "state" / "jobs.jsonl")
    job = manager.create(make_handoff(sandbox_project), "openai", "mock-model")
    job = manager.transition(job, "RUNNING", attempt=1)
    job = manager.transition(job, "FAILED", error_code="MOCK")
    assert job["status"] == "FAILED"


def test_t40_missing_input_price_returns_null_cost():
    assert UsageManager.calculate_cost(
        {"input_tokens": 1000, "output_tokens": 500, "cached_input_tokens": 0},
        {"input_per_million": None, "cached_input_per_million": 0.5, "output_per_million": 2.0},
    ) is None


def test_t41_missing_output_price_returns_null_cost():
    assert UsageManager.calculate_cost(
        {"input_tokens": 1000, "output_tokens": 500, "cached_input_tokens": 0},
        {"input_per_million": 1.0, "cached_input_per_million": 0.5, "output_per_million": None},
    ) is None


def test_t42_cached_tokens_without_cached_price_returns_null_cost():
    assert UsageManager.calculate_cost(
        {"input_tokens": 1000, "output_tokens": 500, "cached_input_tokens": 200},
        {"input_per_million": 1.0, "cached_input_per_million": None, "output_per_million": 2.0},
    ) is None


def test_t43_complete_pricing_calculates_cost():
    assert UsageManager.calculate_cost(
        {"input_tokens": 1000, "output_tokens": 500, "cached_input_tokens": 200},
        {"input_per_million": 1.0, "cached_input_per_million": 0.5, "output_per_million": 2.0},
    ) == 0.0019


def test_t44_same_frozen_handoff_can_be_analyzed_twice_unchanged(sandbox_project):
    provider = FakeProvider([None, None])
    service = make_service(sandbox_project, provider)
    handoff = service.build_handoff(sandbox_project / "samples" / "simulated_event.json")
    original = deepcopy(handoff)
    first = service.analyze_handoff(handoff)
    second = service.analyze_handoff(handoff)
    assert handoff == original
    assert first["handoff"] == second["handoff"] == original
    assert first["handoff"]["handoff_id"] == second["handoff"]["handoff_id"]
    assert first["handoff"]["generated_at"] == second["handoff"]["generated_at"]
    assert first["handoff"]["cursor_snapshot"] == second["handoff"]["cursor_snapshot"]
