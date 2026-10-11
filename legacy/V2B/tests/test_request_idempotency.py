from __future__ import annotations

import json
import threading
from copy import deepcopy

import pytest

from coordinator.action_policy import DEFAULT_ACTION_POLICY
from coordinator.errors import CoordinatorError, ErrorCode
from coordinator.event_manager import EventManager
from coordinator.job_manager import JobManager
from coordinator.request_fingerprint import build_request_fingerprint
from coordinator.service import V2BCoordinator
from tests.helpers import FakeProvider, fake_factory, provider_error
from v2b_coordinator import parser, print_analysis_result


def build_handoff(project):
    manager = EventManager(project / "schemas" / "event_handoff.schema.json")
    return manager.build_handoff(manager.load_event(project / "samples" / "simulated_event.json"))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def fingerprint(
    handoff,
    *,
    reasoning="low",
    policy=None,
    prompt="stable prompt",
    schema=None,
):
    policy = policy or DEFAULT_ACTION_POLICY
    schema = schema or {"type": "object", "properties": {"action": {"type": "string"}}}
    return build_request_fingerprint(
        handoff=handoff,
        provider="deepseek",
        model="deepseek-v4-pro",
        reasoning_effort=reasoning,
        action_policy=policy,
        effective_prompt=prompt,
        decision_schema=schema,
        provider_output_schema=schema,
        provider_request_options={
            "max_output_tokens": None,
            "structured_outputs": True,
            "allow_json_fallback": True,
        },
    )


def make_service(project, provider):
    return V2BCoordinator(
        project,
        provider_factory=fake_factory(provider),
        sleep_fn=lambda _seconds: None,
    )


def analyze(service, handoff, *, reasoning="low", policy="structure_first", force=False):
    return service.analyze_handoff(
        handoff,
        provider_name="deepseek",
        reasoning_effort=reasoning,
        action_policy_mode=policy,
        force=force,
    )


def test_t01_identical_effective_request_has_identical_fingerprint(sandbox_project):
    handoff = build_handoff(sandbox_project)
    reordered = {key: handoff[key] for key in reversed(handoff)}
    assert fingerprint(handoff) == fingerprint(deepcopy(handoff)) == fingerprint(reordered)


def test_t02_reasoning_changes_fingerprint(sandbox_project):
    handoff = build_handoff(sandbox_project)
    assert fingerprint(handoff, reasoning="low") != fingerprint(handoff, reasoning="high")


def test_t03_action_policy_changes_fingerprint(sandbox_project):
    handoff = build_handoff(sandbox_project)
    structure = {**DEFAULT_ACTION_POLICY, "mode": "structure_first"}
    balanced = {**DEFAULT_ACTION_POLICY, "mode": "balanced"}
    assert fingerprint(handoff, policy=structure) != fingerprint(handoff, policy=balanced)


def test_t04_handoff_content_changes_fingerprint(sandbox_project):
    handoff = build_handoff(sandbox_project)
    changed = deepcopy(handoff)
    changed["current_state"]["price"] += 0.01
    assert fingerprint(handoff) != fingerprint(changed)


def test_prompt_and_schema_changes_also_change_fingerprint(sandbox_project):
    handoff = build_handoff(sandbox_project)
    base = fingerprint(handoff)
    assert base != fingerprint(handoff, prompt="different prompt")
    assert base != fingerprint(handoff, schema={"type": "object", "additionalProperties": False})


def test_t05_t06_successful_second_request_is_reused_across_coordinator_instances(sandbox_project):
    handoff = build_handoff(sandbox_project)
    first_provider = FakeProvider()
    first = analyze(make_service(sandbox_project, first_provider), handoff)
    jobs_after_first = (sandbox_project / "state" / "jobs.jsonl").read_bytes()
    decisions_after_first = (sandbox_project / "state" / "decisions.jsonl").read_bytes()

    second_provider = FakeProvider()
    second = analyze(make_service(sandbox_project, second_provider), handoff)

    assert first["job"]["status"] == "RESULT_READY"
    assert first["api_called"] is True and first["reused"] is False
    assert second["job"]["status"] == "RESULT_READY"
    assert second["api_called"] is False and second["reused"] is True
    assert second_provider.calls == 0
    assert second["job"]["job_id"] == first["job"]["job_id"]
    assert second["decision"]["decision_id"] == first["decision"]["decision_id"]
    assert second["request_fingerprint"] == first["request_fingerprint"]
    assert (sandbox_project / "state" / "jobs.jsonl").read_bytes() == jobs_after_first
    assert (sandbox_project / "state" / "decisions.jsonl").read_bytes() == decisions_after_first


def test_result_ready_without_its_decision_is_not_reused(sandbox_project):
    handoff = build_handoff(sandbox_project)
    provider = FakeProvider([None, None])
    service = make_service(sandbox_project, provider)
    first = analyze(service, handoff)
    (sandbox_project / "state" / "decisions.jsonl").write_text("", encoding="utf-8")

    second = analyze(service, handoff)

    assert provider.calls == 2
    assert second["api_called"] is True and second["reused"] is False
    assert second["job"]["job_id"] != first["job"]["job_id"]


def test_t07_force_creates_new_job_and_decision_with_same_fingerprint(sandbox_project):
    handoff = build_handoff(sandbox_project)
    provider = FakeProvider([None, None])
    service = make_service(sandbox_project, provider)
    first = analyze(service, handoff)
    forced = analyze(service, handoff, force=True)

    assert forced["api_called"] is True and forced["reused"] is False and forced["forced"] is True
    assert forced["job"]["job_id"] != first["job"]["job_id"]
    assert forced["decision"]["decision_id"] != first["decision"]["decision_id"]
    assert forced["request_fingerprint"] == first["request_fingerprint"]
    assert provider.calls == 2
    forced_jobs = [
        job for job in read_jsonl(sandbox_project / "state" / "jobs.jsonl")
        if job["job_id"] == forced["job"]["job_id"]
    ]
    assert [job["status"] for job in forced_jobs] == ["QUEUED", "RUNNING", "RESULT_READY"]
    assert all(job["forced"] is True for job in forced_jobs)
    assert {job["request_fingerprint"] for job in forced_jobs} == {first["request_fingerprint"]}


def test_t08_failed_request_is_allowed_to_run_again(sandbox_project):
    handoff = build_handoff(sandbox_project)
    provider = FakeProvider([
        provider_error(ErrorCode.PROVIDER_ERROR, retryable=False),
        None,
    ])
    service = make_service(sandbox_project, provider)

    with pytest.raises(CoordinatorError):
        analyze(service, handoff)
    failed_job = read_jsonl(sandbox_project / "state" / "jobs.jsonl")[-1]
    succeeded = analyze(service, handoff)

    assert failed_job["status"] == "FAILED"
    assert succeeded["api_called"] is True and succeeded["reused"] is False
    assert succeeded["job"]["job_id"] != failed_job["job_id"]
    assert succeeded["request_fingerprint"] == failed_job["request_fingerprint"]
    assert provider.calls == 2


def test_failed_forced_rerun_does_not_hide_an_earlier_valid_success(sandbox_project):
    handoff = build_handoff(sandbox_project)
    provider = FakeProvider([
        None,
        provider_error(ErrorCode.PROVIDER_ERROR, retryable=False),
    ])
    service = make_service(sandbox_project, provider)
    first = analyze(service, handoff)
    with pytest.raises(CoordinatorError):
        analyze(service, handoff, force=True)

    fallback_provider = FakeProvider()
    reused = analyze(make_service(sandbox_project, fallback_provider), handoff)

    assert reused["reused"] is True and reused["api_called"] is False
    assert reused["job"]["job_id"] == first["job"]["job_id"]
    assert reused["decision"]["decision_id"] == first["decision"]["decision_id"]
    assert fallback_provider.calls == 0


@pytest.mark.parametrize("active_status", ["QUEUED", "RUNNING"])
def test_t09_active_identical_request_does_not_start_second_job_even_with_force(sandbox_project, active_status):
    handoff = build_handoff(sandbox_project)
    provider = FakeProvider()
    service = make_service(sandbox_project, provider)
    completed = analyze(service, handoff)
    manager = JobManager(sandbox_project / "state" / "jobs.jsonl")
    active = manager.create(
        handoff,
        "deepseek",
        "deepseek-v4-pro",
        reasoning_effort="low",
        action_policy=DEFAULT_ACTION_POLICY,
        request_fingerprint=completed["request_fingerprint"],
        forced=False,
    )
    if active_status == "RUNNING":
        active = manager.transition(active, "RUNNING", attempt=1)
    job_bytes = (sandbox_project / "state" / "jobs.jsonl").read_bytes()

    duplicate_provider = FakeProvider()
    duplicate = analyze(make_service(sandbox_project, duplicate_provider), handoff, force=True)

    assert duplicate["status"] == "JOB_IN_PROGRESS"
    assert duplicate["reused"] is True and duplicate["api_called"] is False
    assert duplicate["job"]["job_id"] == active["job_id"]
    assert duplicate_provider.calls == 0
    assert (sandbox_project / "state" / "jobs.jsonl").read_bytes() == job_bytes


def test_t10_legacy_job_without_fingerprint_is_ignored(sandbox_project):
    handoff = build_handoff(sandbox_project)
    legacy = {
        "schema_version": "1.0",
        "job_id": "JOB-LEGACY",
        "handoff_id": handoff["handoff_id"],
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "status": "RESULT_READY",
        "decision_id": "DEC-LEGACY",
    }
    path = sandbox_project / "state" / "jobs.jsonl"
    path.write_text(json.dumps(legacy, ensure_ascii=False) + "\n", encoding="utf-8")
    provider = FakeProvider()

    result = analyze(make_service(sandbox_project, provider), handoff)

    assert result["api_called"] is True and result["reused"] is False
    assert provider.calls == 1
    assert read_jsonl(path)[0] == legacy


def test_concurrent_identical_claims_create_only_one_job_and_one_provider_call(sandbox_project):
    handoff = build_handoff(sandbox_project)
    provider_started = threading.Event()
    release_provider = threading.Event()
    one_worker_finished = threading.Event()
    start_gate = threading.Barrier(3)
    results = []
    errors = []
    result_lock = threading.Lock()

    class BlockingProvider(FakeProvider):
        def analyze_event(self, current_handoff, *, request_context=None):
            provider_started.set()
            if not release_provider.wait(5):
                raise AssertionError("test provider was not released")
            return super().analyze_event(current_handoff, request_context=request_context)

    providers = [BlockingProvider(), BlockingProvider()]
    services = [make_service(sandbox_project, provider) for provider in providers]

    def worker(service):
        try:
            start_gate.wait()
            result = analyze(service, handoff)
            with result_lock:
                results.append(result)
        except Exception as error:  # pragma: no cover - surfaced by assertion below
            with result_lock:
                errors.append(error)
        finally:
            one_worker_finished.set()

    threads = [threading.Thread(target=worker, args=(service,)) for service in services]
    for thread in threads:
        thread.start()
    start_gate.wait()
    assert provider_started.wait(2)
    assert one_worker_finished.wait(2)
    release_provider.set()
    for thread in threads:
        thread.join(5)

    assert not errors
    assert len(results) == 2
    assert sum(provider.calls for provider in providers) == 1
    assert {result.get("status", result["job"]["status"]) for result in results} == {
        "JOB_IN_PROGRESS",
        "RESULT_READY",
    }
    assert len({result["job"]["job_id"] for result in results}) == 1
    jobs = read_jsonl(sandbox_project / "state" / "jobs.jsonl")
    assert [job["status"] for job in jobs] == ["QUEUED", "RUNNING", "RESULT_READY"]


def test_different_reasoning_and_policy_combinations_are_not_reused(sandbox_project):
    handoff = build_handoff(sandbox_project)
    provider = FakeProvider([None, None, None, None])
    service = make_service(sandbox_project, provider)
    combinations = [
        ("low", "structure_first"),
        ("low", "balanced"),
        ("low", "key_level_first"),
        ("high", "structure_first"),
    ]
    results = [analyze(service, handoff, reasoning=reasoning, policy=policy) for reasoning, policy in combinations]
    assert provider.calls == 4
    assert all(result["api_called"] is True and result["reused"] is False for result in results)
    assert len({result["request_fingerprint"] for result in results}) == 4


def test_cli_force_and_reused_output_fields(capsys):
    args = parser().parse_args([
        "analyze-handoff",
        "--handoff",
        "state/last_simulated_handoff.json",
        "--force",
    ])
    assert args.force is True
    result = {
        "job": {"status": "RESULT_READY", "job_id": "JOB-1"},
        "decision": {
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "decision_id": "DEC-1",
            "action": "WATCH",
        },
        "usage": [],
        "reasoning_effort": "low",
        "action_policy": "structure_first",
        "request_fingerprint": "a" * 64,
        "reused": True,
        "api_called": False,
        "forced": False,
    }
    assert print_analysis_result(result) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["reused"] is True
    assert output["api_called"] is False
    assert output["request_fingerprint"] == "a" * 64
