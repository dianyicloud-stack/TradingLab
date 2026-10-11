from __future__ import annotations

import json

import pytest
import yaml

from coordinator.errors import CoordinatorError, ErrorCode
from coordinator.service import V2BCoordinator
from tests.helpers import FakeProvider, fake_factory, provider_error, valid_analysis


def configure_retries(project, retries: int) -> None:
    path = project / "config.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["ai"]["providers"]["openai"]["max_retries"] = retries
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")


def coordinator(project, fake: FakeProvider, sleeps=None) -> V2BCoordinator:
    sleeps = sleeps if sleeps is not None else []
    return V2BCoordinator(
        project,
        session_provider="openai",
        provider_factory=fake_factory(fake),
        sleep_fn=lambda seconds: sleeps.append(seconds),
    )


def event_path(project):
    return project / "samples" / "simulated_event.json"


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_t07_mock_provider_to_decision(sandbox_project):
    result = coordinator(sandbox_project, FakeProvider()).analyze(event_path(sandbox_project))
    assert result["job"]["status"] == "RESULT_READY"
    assert result["decision"]["provider"] == "openai"
    assert result["decision"]["action"] == "WATCH"
    assert result["usage"][0]["cost_usd"] is None


@pytest.mark.parametrize(
    ("code", "test_id"),
    [
        (ErrorCode.TIMEOUT, "T12"),
        (ErrorCode.RATE_LIMITED, "T13"),
        (ErrorCode.PROVIDER_ERROR, "T14"),
    ],
)
def test_t12_t14_transient_provider_failure(sandbox_project, code, test_id):
    del test_id
    configure_retries(sandbox_project, 0)
    fake = FakeProvider([provider_error(code, retryable=True)])
    service = coordinator(sandbox_project, fake)
    with pytest.raises(CoordinatorError) as caught:
        service.analyze(event_path(sandbox_project))
    assert caught.value.code == code
    jobs = read_jsonl(sandbox_project / "state" / "jobs.jsonl")
    assert jobs[-1]["status"] == "FAILED"
    assert jobs[-1]["error_code"] == code.value


def test_t15_finite_retry_then_success(sandbox_project):
    configure_retries(sandbox_project, 2)
    sleeps = []
    fake = FakeProvider([
        provider_error(ErrorCode.TIMEOUT, retryable=True),
        provider_error(ErrorCode.RATE_LIMITED, retryable=True),
        None,
    ])
    result = coordinator(sandbox_project, fake, sleeps).analyze(event_path(sandbox_project))
    assert result["job"]["status"] == "RESULT_READY"
    assert fake.calls == 3
    assert sleeps == [1.0, 2.0]


def test_t16_job_state_path(sandbox_project):
    coordinator(sandbox_project, FakeProvider()).analyze(event_path(sandbox_project))
    statuses = [item["status"] for item in read_jsonl(sandbox_project / "state" / "jobs.jsonl")]
    assert statuses == ["QUEUED", "RUNNING", "RESULT_READY"]


def test_t17_failed_job_is_persisted(sandbox_project):
    invalid = valid_analysis({"cursor_snapshot": {"handoff_max_event_seq": 17, "handoff_max_observation_time": "10:15"}})
    invalid["action"] = "BUY"
    service = coordinator(sandbox_project, FakeProvider([invalid]))
    with pytest.raises(CoordinatorError) as caught:
        service.analyze(event_path(sandbox_project))
    assert caught.value.code == ErrorCode.SCHEMA_VALIDATION_FAILED
    assert read_jsonl(sandbox_project / "state" / "jobs.jsonl")[-1]["status"] == "FAILED"


def test_t18_jobs_jsonl_is_append_only(sandbox_project):
    service = coordinator(sandbox_project, FakeProvider([None, None]))
    service.analyze(event_path(sandbox_project))
    path = sandbox_project / "state" / "jobs.jsonl"
    first_bytes = path.read_bytes()
    service.analyze(event_path(sandbox_project))
    second_bytes = path.read_bytes()
    assert second_bytes.startswith(first_bytes)
    assert len(read_jsonl(path)) == 6


def test_t19_decisions_jsonl_is_append_only(sandbox_project):
    service = coordinator(sandbox_project, FakeProvider([None, None]))
    service.analyze(event_path(sandbox_project))
    path = sandbox_project / "state" / "decisions.jsonl"
    first_bytes = path.read_bytes()
    service.analyze(event_path(sandbox_project))
    second_bytes = path.read_bytes()
    assert second_bytes.startswith(first_bytes)
    assert len(read_jsonl(path)) == 2


def test_t20_usage_and_logs_do_not_contain_api_key(sandbox_project):
    secret = "unit-test-secret-should-not-log"
    configure_retries(sandbox_project, 0)
    fake = FakeProvider([provider_error(ErrorCode.PROVIDER_ERROR, retryable=False, message=f"Authorization: {secret}")])
    service = coordinator(sandbox_project, fake)
    with pytest.raises(CoordinatorError):
        service.analyze(event_path(sandbox_project))
    combined = (
        (sandbox_project / "logs" / "api_usage.jsonl").read_text(encoding="utf-8")
        + (sandbox_project / "logs" / "coordinator.log").read_text(encoding="utf-8")
    )
    assert secret not in combined
    assert "Authorization" not in combined
