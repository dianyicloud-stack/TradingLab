from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import openai
import pytest

from coordinator.config_manager import ConfigManager
from coordinator.decision_manager import DecisionManager
from coordinator.errors import CoordinatorError, ErrorCode
from coordinator.event_manager import EventManager
from coordinator.service import V2BCoordinator
from providers import build_provider
from providers.deepseek_provider import DeepSeekProvider
from tests.helpers import valid_analysis


class StatusError(RuntimeError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = "req_deepseek_error"


class FakeResponses:
    def __init__(
        self,
        handoff,
        outcomes=None,
        *,
        reasoning_secret: str | None = None,
        output_texts=None,
        response_status: str = "completed",
        finish_reason: str | None = None,
    ) -> None:
        self.handoff = handoff
        self.outcomes = list(outcomes or [])
        self.reasoning_secret = reasoning_secret
        self.output_texts = list(output_texts or [])
        self.response_status = response_status
        self.finish_reason = finish_reason
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
        usage = SimpleNamespace(
            input_tokens=700,
            output_tokens=180,
            total_tokens=880,
            input_tokens_details=SimpleNamespace(cached_tokens=70),
            output_tokens_details=SimpleNamespace(reasoning_tokens=90),
        )
        return SimpleNamespace(
            id="resp_deepseek_mock",
            _request_id="req_deepseek_mock",
            status=self.response_status,
            incomplete_details=SimpleNamespace(reason=self.finish_reason) if self.finish_reason else None,
            output_text=(
                self.output_texts.pop(0)
                if self.output_texts
                else json.dumps(valid_analysis(self.handoff), ensure_ascii=False)
            ),
            output=[SimpleNamespace(type="reasoning", content=self.reasoning_secret)],
            reasoning_content=self.reasoning_secret,
            usage=usage,
        )


def handoff(project):
    event_manager = EventManager(project / "schemas" / "event_handoff.schema.json")
    return event_manager.build_handoff(
        event_manager.load_event(project / "samples" / "simulated_event.json")
    )


def provider_config(project):
    return ConfigManager(project).provider_config("deepseek")


def make_provider(monkeypatch, project, fake_responses):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-deepseek-key")
    client = SimpleNamespace(responses=fake_responses)
    decision_manager = DecisionManager(project / "schemas" / "decision.schema.json")
    provider = DeepSeekProvider(
        provider_config(project),
        prompt="test prompt",
        output_schema=decision_manager.provider_output_schema(),
        client=client,
    )
    provider.configure_decision_schema(decision_manager.analysis_schema())
    return provider


def test_deepseek_registry_is_implemented(sandbox_project):
    report = {item["provider"]: item for item in ConfigManager(sandbox_project).providers_report()}
    assert report["openai"]["implemented"] is True
    assert report["deepseek"]["implemented"] is True
    assert report["minimax"]["implemented"] is False
    assert report["volcengine"]["implemented"] is False
    assert report["qwen"]["implemented"] is False


def test_deepseek_disabled_returns_provider_disabled(sandbox_project):
    config = provider_config(sandbox_project)
    config["enabled"] = False
    with pytest.raises(CoordinatorError) as caught:
        build_provider("deepseek", config, prompt="test", output_schema={"type": "object"})
    assert caught.value.code == ErrorCode.PROVIDER_DISABLED


def test_deepseek_missing_api_key_returns_api_key_missing(sandbox_project, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(CoordinatorError) as caught:
        DeepSeekProvider(
            provider_config(sandbox_project),
            prompt="test",
            output_schema={"type": "object"},
        )
    assert caught.value.code == ErrorCode.API_KEY_MISSING


def test_deepseek_client_uses_official_base_url_and_no_sdk_retry(sandbox_project, monkeypatch):
    import providers.deepseek_provider as module

    captured = {}
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-deepseek-key")
    monkeypatch.setattr(
        module,
        "OpenAI",
        lambda **kwargs: captured.update(kwargs) or SimpleNamespace(responses=SimpleNamespace()),
    )
    provider = DeepSeekProvider(
        provider_config(sandbox_project),
        prompt="test",
        output_schema={"type": "object"},
    )
    assert provider.base_url == "https://api.deepseek.com"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["timeout"] == 90
    assert captured["max_retries"] == 0


def test_deepseek_model_is_read_from_config(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    provider = make_provider(monkeypatch, sandbox_project, FakeResponses(current_handoff))
    assert provider.model == "deepseek-v4-pro"


def test_deepseek_uses_responses_api_with_thinking_parameters(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    responses = FakeResponses(current_handoff)
    provider = make_provider(monkeypatch, sandbox_project, responses)
    provider.analyze_event(current_handoff)
    request = responses.calls[0]
    assert request["model"] == "deepseek-v4-pro"
    assert request["reasoning"] == {"effort": "none"}
    assert "max_output_tokens" not in request
    assert json.loads(request["input"])["handoff_id"] == current_handoff["handoff_id"]
    assert "JSON" in request["instructions"]
    assert "Return exactly one valid JSON object." in request["instructions"]
    assert "Do not output Markdown." in request["instructions"]
    assert "Do not output code fences." in request["instructions"]
    assert "Do not output commentary before or after the JSON." in request["instructions"]
    assert "Do not add fields not defined by the schema." in request["instructions"]
    assert "The response MUST satisfy the supplied Decision Schema." in request["instructions"]
    assert "reason_summary must contain no more than 5 items." in request["instructions"]
    assert "Each reason_summary item must contain no more than 300 characters." in request["instructions"]
    assert "temperature" not in request
    assert "top_p" not in request


@pytest.mark.parametrize("reasoning_effort", ["none", "low", "high", "max"])
def test_deepseek_sends_each_supported_reasoning_effort(
    sandbox_project,
    monkeypatch,
    reasoning_effort,
):
    current_handoff = handoff(sandbox_project)
    responses = FakeResponses(current_handoff)
    config = provider_config(sandbox_project)
    config["reasoning_effort"] = reasoning_effort
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-deepseek-key")
    provider = DeepSeekProvider(
        config,
        prompt="test prompt",
        output_schema=DecisionManager(
            sandbox_project / "schemas" / "decision.schema.json"
        ).provider_output_schema(),
        client=SimpleNamespace(responses=responses),
    )

    provider.analyze_event(current_handoff)

    assert responses.calls[0]["reasoning"] == {"effort": reasoning_effort}
    assert "max_output_tokens" not in responses.calls[0]


def test_deepseek_explicit_max_output_tokens_is_sent(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    responses = FakeResponses(current_handoff)
    config = provider_config(sandbox_project)
    config["max_output_tokens"] = 2400
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-deepseek-key")
    provider = DeepSeekProvider(
        config,
        prompt="test prompt",
        output_schema={"type": "object"},
        client=SimpleNamespace(responses=responses),
    )

    provider.analyze_event(current_handoff)

    assert responses.calls[0]["max_output_tokens"] == 2400


def test_deepseek_invalid_reasoning_effort_is_rejected(sandbox_project, monkeypatch):
    config = provider_config(sandbox_project)
    config["reasoning_effort"] = "medium"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-deepseek-key")

    with pytest.raises(CoordinatorError) as caught:
        DeepSeekProvider(config, prompt="test prompt", output_schema={"type": "object"})

    assert caught.value.code == ErrorCode.CONFIG_ERROR


def test_deepseek_prefers_json_schema_structured_output(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    responses = FakeResponses(current_handoff)
    provider = make_provider(monkeypatch, sandbox_project, responses)
    result = provider.analyze_event(current_handoff)
    output_format = responses.calls[0]["text"]["format"]
    assert output_format["type"] == "json_schema"
    assert set(output_format) == {"type", "name", "schema"}
    assert output_format["name"] == "v2b_market_event_decision"
    assert output_format["schema"]["type"] == "object"
    assert output_format["schema"] == provider.output_schema
    assert "schema" not in output_format["schema"]
    assert result["structured_output"] is True


def test_deepseek_structured_output_unavailable_uses_logged_json_fallback(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    responses = FakeResponses(
        current_handoff,
        outcomes=[StatusError("json_schema structured output unsupported", 400), None],
    )
    provider = make_provider(monkeypatch, sandbox_project, responses)
    result = provider.analyze_event(current_handoff)
    assert len(responses.calls) == 2
    assert responses.calls[1]["text"]["format"]["type"] == "json_object"
    assert result["fallback_used"] is True
    assert result["usage_records"][0]["error_type"] == "STRUCTURED_OUTPUT_UNAVAILABLE"
    assert result["usage_records"][1]["fallback_used"] is True


def test_deepseek_empty_response_retries_then_succeeds(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    valid_json = json.dumps(valid_analysis(current_handoff), ensure_ascii=False)
    responses = FakeResponses(current_handoff, output_texts=[None, "   ", valid_json])
    provider = make_provider(monkeypatch, sandbox_project, responses)

    result = provider.analyze_event(current_handoff)

    assert len(responses.calls) == 3
    assert [item["error_type"] for item in result["usage_records"]] == [
        ErrorCode.EMPTY_PROVIDER_RESPONSE.value,
        ErrorCode.EMPTY_PROVIDER_RESPONSE.value,
        None,
    ]
    assert result["analysis"]["action"] == "WATCH"


def test_deepseek_three_empty_responses_return_diagnostic_error(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    responses = FakeResponses(
        current_handoff,
        output_texts=[None, "", "\n\t"],
        response_status="incomplete",
        finish_reason="max_output_tokens",
    )
    provider = make_provider(monkeypatch, sandbox_project, responses)

    with pytest.raises(CoordinatorError) as caught:
        provider.analyze_event(current_handoff)

    assert caught.value.code == ErrorCode.EMPTY_PROVIDER_RESPONSE
    assert len(responses.calls) == 3
    assert "provider=deepseek" in caught.value.message
    assert "model=deepseek-v4-pro" in caught.value.message
    assert "attempts=3" in caught.value.message
    assert "api_type=responses" in caught.value.message
    assert "response_status=incomplete" in caught.value.message
    assert "finish_reason=max_output_tokens" in caught.value.message
    assert "Expecting value" not in caught.value.message


def test_deepseek_non_json_response_has_safe_diagnostics(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    raw_text = "not-json secret=unit-test-deepseek-key"
    responses = FakeResponses(current_handoff, output_texts=[raw_text])
    provider = make_provider(monkeypatch, sandbox_project, responses)

    with pytest.raises(CoordinatorError) as caught:
        provider.analyze_event(current_handoff)

    assert caught.value.code == ErrorCode.INVALID_RESPONSE
    assert len(responses.calls) == 1
    assert f"raw_content_length={len(raw_text)}" in caught.value.message
    assert "raw_preview='not-json secret=[REDACTED]'" in caught.value.message
    assert "response_status=completed" in caught.value.message


def test_deepseek_does_not_repair_markdown_code_fences(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    raw_text = "```json\n{}\n```"
    responses = FakeResponses(current_handoff, output_texts=[raw_text])
    provider = make_provider(monkeypatch, sandbox_project, responses)

    with pytest.raises(CoordinatorError) as caught:
        provider.analyze_event(current_handoff)

    assert caught.value.code == ErrorCode.INVALID_RESPONSE
    assert len(responses.calls) == 1


def test_deepseek_empty_retries_do_not_create_extra_job_records(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    valid_json = json.dumps(valid_analysis(current_handoff), ensure_ascii=False)
    responses = FakeResponses(current_handoff, output_texts=[None, "", valid_json])
    provider = make_provider(monkeypatch, sandbox_project, responses)
    service = V2BCoordinator(
        sandbox_project,
        provider_factory=lambda _name, _config, _prompt, _schema: provider,
        sleep_fn=lambda _seconds: None,
    )

    result = service.analyze_handoff(current_handoff)
    jobs = [
        json.loads(line)
        for line in (sandbox_project / "state" / "jobs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    decisions = [
        json.loads(line)
        for line in (sandbox_project / "state" / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(responses.calls) == 3
    assert [item["status"] for item in jobs] == ["QUEUED", "RUNNING", "RESULT_READY"]
    assert len(decisions) == 1
    assert result["decision"]["processed_through_seq"] == 17
    assert result["decision"]["processed_through_observation_time"] == "10:15"


def test_deepseek_schema_failure_is_repaired_once(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    invalid_analysis = valid_analysis(current_handoff)
    invalid_analysis["reason_summary"] = [f"reason {index}" for index in range(6)]
    repaired_analysis = valid_analysis(current_handoff)
    responses = FakeResponses(
        current_handoff,
        output_texts=[
            json.dumps(invalid_analysis, ensure_ascii=False),
            json.dumps(repaired_analysis, ensure_ascii=False),
        ],
    )
    provider = make_provider(monkeypatch, sandbox_project, responses)
    service = V2BCoordinator(
        sandbox_project,
        provider_factory=lambda _name, _config, _prompt, _schema: provider,
        sleep_fn=lambda _seconds: None,
    )

    result = service.analyze_handoff(current_handoff)

    assert len(responses.calls) == 2
    repair_request = responses.calls[1]
    repair_payload = json.loads(repair_request["input"])
    assert len(repair_payload["original_decision_json"]["reason_summary"]) == 6
    assert "reason_summary" in repair_payload["validator_error"]
    reason_schema = repair_payload["decision_schema"]["properties"]["reason_summary"]
    assert reason_schema["maxItems"] == 5
    assert reason_schema["items"]["maxLength"] == 300
    assert "Repair the JSON only." in repair_request["instructions"]
    assert "Preserve the analytical conclusion." in repair_request["instructions"]
    assert "Do not introduce new analysis." in repair_request["instructions"]
    assert result["job"]["status"] == "RESULT_READY"
    assert result["decision"]["reason_summary"] == repaired_analysis["reason_summary"]
    assert result["decision"]["processed_through_seq"] == 17
    assert result["decision"]["processed_through_observation_time"] == "10:15"


def test_deepseek_schema_repair_failure_is_not_retried_again(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    invalid_analysis = valid_analysis(current_handoff)
    invalid_analysis["reason_summary"] = [f"reason {index}" for index in range(6)]
    invalid_json = json.dumps(invalid_analysis, ensure_ascii=False)
    responses = FakeResponses(current_handoff, output_texts=[invalid_json, invalid_json])
    provider = make_provider(monkeypatch, sandbox_project, responses)
    service = V2BCoordinator(
        sandbox_project,
        provider_factory=lambda _name, _config, _prompt, _schema: provider,
        sleep_fn=lambda _seconds: None,
    )

    with pytest.raises(CoordinatorError) as caught:
        service.analyze_handoff(current_handoff)

    jobs = [
        json.loads(line)
        for line in (sandbox_project / "state" / "jobs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    decisions = (sandbox_project / "state" / "decisions.jsonl").read_text(encoding="utf-8")
    assert caught.value.code == ErrorCode.SCHEMA_VALIDATION_FAILED
    assert "reason_summary" in caught.value.message
    assert len(responses.calls) == 2
    assert [item["status"] for item in jobs] == ["QUEUED", "RUNNING", "FAILED"]
    assert decisions == ""


def test_deepseek_final_empty_response_writes_no_decision_or_retry_jobs(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    responses = FakeResponses(current_handoff, output_texts=[None, "", "   "])
    provider = make_provider(monkeypatch, sandbox_project, responses)
    service = V2BCoordinator(
        sandbox_project,
        provider_factory=lambda _name, _config, _prompt, _schema: provider,
        sleep_fn=lambda _seconds: None,
    )

    with pytest.raises(CoordinatorError) as caught:
        service.analyze_handoff(current_handoff)

    jobs = [
        json.loads(line)
        for line in (sandbox_project / "state" / "jobs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    decisions = (sandbox_project / "state" / "decisions.jsonl").read_text(encoding="utf-8")
    assert caught.value.code == ErrorCode.EMPTY_PROVIDER_RESPONSE
    assert len(responses.calls) == 3
    assert len({item["job_id"] for item in jobs}) == 1
    assert [item["status"] for item in jobs] == ["QUEUED", "RUNNING", "FAILED"]
    assert decisions == ""


def test_deepseek_analysis_builds_valid_unified_decision(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    provider = make_provider(monkeypatch, sandbox_project, FakeResponses(current_handoff))
    result = provider.analyze_event(current_handoff)
    decision_manager = DecisionManager(sandbox_project / "schemas" / "decision.schema.json")
    decision = decision_manager.build_decision(
        result["analysis"],
        handoff=current_handoff,
        provider="deepseek",
        model=provider.model,
    )
    decision_manager.validate_decision(decision, current_handoff)
    assert decision["provider"] == "deepseek"
    assert decision["action"] == "WATCH"


def test_deepseek_cannot_override_system_owned_cursors(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    responses = FakeResponses(current_handoff)
    provider = make_provider(monkeypatch, sandbox_project, responses)
    result = provider.analyze_event(current_handoff)
    result["analysis"]["processed_through_seq"] = 999999
    result["analysis"]["processed_through_observation_time"] = "23:59"
    decision = DecisionManager(sandbox_project / "schemas" / "decision.schema.json").build_decision(
        result["analysis"],
        handoff=current_handoff,
        provider="deepseek",
        model=provider.model,
    )
    assert decision["processed_through_seq"] == current_handoff["cursor_snapshot"]["handoff_max_event_seq"]
    assert decision["processed_through_observation_time"] == current_handoff["cursor_snapshot"]["handoff_max_observation_time"]


def test_deepseek_timeout_is_retryable(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    timeout = openai.APITimeoutError(request=httpx.Request("POST", "https://api.deepseek.com/responses"))
    provider = make_provider(monkeypatch, sandbox_project, FakeResponses(current_handoff, [timeout]))
    with pytest.raises(CoordinatorError) as caught:
        provider.analyze_event(current_handoff)
    assert caught.value.code == ErrorCode.TIMEOUT
    assert caught.value.retryable is True


def test_deepseek_429_is_retryable(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    provider = make_provider(
        monkeypatch,
        sandbox_project,
        FakeResponses(current_handoff, [StatusError("rate limited", 429)]),
    )
    with pytest.raises(CoordinatorError) as caught:
        provider.analyze_event(current_handoff)
    assert caught.value.code == ErrorCode.RATE_LIMITED
    assert caught.value.retryable is True


def test_deepseek_401_is_not_retryable(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    provider = make_provider(
        monkeypatch,
        sandbox_project,
        FakeResponses(current_handoff, [StatusError("unauthorized", 401)]),
    )
    with pytest.raises(CoordinatorError) as caught:
        provider.analyze_event(current_handoff)
    assert caught.value.code == ErrorCode.AUTH_FAILED
    assert caught.value.retryable is False


def test_deepseek_5xx_is_retryable(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    provider = make_provider(
        monkeypatch,
        sandbox_project,
        FakeResponses(current_handoff, [StatusError("upstream unavailable", 503)]),
    )
    with pytest.raises(CoordinatorError) as caught:
        provider.analyze_event(current_handoff)
    assert caught.value.code == ErrorCode.PROVIDER_ERROR
    assert caught.value.retryable is True


def test_deepseek_usage_mapping_includes_reasoning_tokens(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    provider = make_provider(monkeypatch, sandbox_project, FakeResponses(current_handoff))
    usage = provider.analyze_event(current_handoff)["usage_records"][0]
    assert usage["request_id"] == "req_deepseek_mock"
    assert usage["input_tokens"] == 700
    assert usage["output_tokens"] == 180
    assert usage["total_tokens"] == 880
    assert usage["cached_input_tokens"] == 70
    assert usage["reasoning_tokens"] == 90
    assert usage["latency_ms"] is not None


def test_deepseek_reasoning_text_is_not_persisted(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    secret = "PRIVATE_REASONING_TEXT_MUST_NOT_PERSIST"
    provider = make_provider(
        monkeypatch,
        sandbox_project,
        FakeResponses(current_handoff, reasoning_secret=secret),
    )
    service = V2BCoordinator(
        sandbox_project,
        provider_factory=lambda _name, _config, _prompt, _schema: provider,
        sleep_fn=lambda _seconds: None,
    )
    result = service.analyze_handoff(current_handoff)
    persisted = (
        json.dumps(result, ensure_ascii=False)
        + (sandbox_project / "state" / "decisions.jsonl").read_text(encoding="utf-8")
        + (sandbox_project / "logs" / "api_usage.jsonl").read_text(encoding="utf-8")
        + (sandbox_project / "logs" / "coordinator.log").read_text(encoding="utf-8")
    )
    assert secret not in persisted
    assert result["usage"][0]["reasoning_tokens"] == 90


def test_deepseek_frozen_handoff_is_unchanged_after_analysis(sandbox_project, monkeypatch):
    current_handoff = handoff(sandbox_project)
    before = deepcopy(current_handoff)
    provider = make_provider(monkeypatch, sandbox_project, FakeResponses(current_handoff))
    service = V2BCoordinator(
        sandbox_project,
        provider_factory=lambda _name, _config, _prompt, _schema: provider,
        sleep_fn=lambda _seconds: None,
    )
    result = service.analyze_handoff(current_handoff)
    assert current_handoff == before
    assert result["handoff"] == before
