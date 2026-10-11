from __future__ import annotations

import json
from types import SimpleNamespace

from coordinator.event_manager import EventManager
from providers.base import AIProvider
from providers.openai_provider import OpenAIProvider
from tests.helpers import FakeProvider, valid_analysis


def test_provider_implements_shared_interface():
    provider = FakeProvider()
    assert isinstance(provider, AIProvider)
    assert callable(provider.analyze_event)


class FakeResponses:
    def __init__(self, handoff, *, fail_structured=False):
        self.handoff = handoff
        self.fail_structured = fail_structured
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_structured and len(self.calls) == 1:
            error = RuntimeError("json_schema structured output is unsupported")
            error.status_code = 400
            error.request_id = "req_structured_failed"
            raise error
        usage = SimpleNamespace(
            input_tokens=400,
            output_tokens=100,
            total_tokens=500,
            input_tokens_details=SimpleNamespace(cached_tokens=40),
        )
        return SimpleNamespace(
            id="resp_mock",
            _request_id="req_mock_openai",
            output_text=json.dumps(valid_analysis(self.handoff), ensure_ascii=False),
            usage=usage,
        )


def make_openai_provider(monkeypatch, handoff, *, fail_structured=False):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-provider-key")
    responses = FakeResponses(handoff, fail_structured=fail_structured)
    client = SimpleNamespace(responses=responses)
    provider = OpenAIProvider(
        {
            "model": "mock-model",
            "api_key_env": "OPENAI_API_KEY",
            "structured_outputs": True,
            "allow_json_fallback": True,
        },
        prompt="test prompt",
        output_schema={"type": "object", "additionalProperties": True},
        client=client,
    )
    return provider, responses


def test_openai_provider_uses_responses_structured_outputs(sandbox_project, monkeypatch):
    manager = EventManager(sandbox_project / "schemas" / "event_handoff.schema.json")
    handoff = manager.build_handoff(manager.load_event(sandbox_project / "samples" / "simulated_event.json"))
    provider, responses = make_openai_provider(monkeypatch, handoff)
    result = provider.analyze_event(handoff)
    request = responses.calls[0]
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    assert request["store"] is False
    assert result["structured_output"] is True
    assert result["usage_records"][0]["cached_input_tokens"] == 40


def test_openai_provider_records_json_fallback(sandbox_project, monkeypatch):
    manager = EventManager(sandbox_project / "schemas" / "event_handoff.schema.json")
    handoff = manager.build_handoff(manager.load_event(sandbox_project / "samples" / "simulated_event.json"))
    provider, responses = make_openai_provider(monkeypatch, handoff, fail_structured=True)
    result = provider.analyze_event(handoff)
    assert len(responses.calls) == 2
    assert "text" in responses.calls[0]
    assert "text" not in responses.calls[1]
    assert result["fallback_used"] is True
    assert result["usage_records"][0]["error_type"] == "STRUCTURED_OUTPUT_UNAVAILABLE"
