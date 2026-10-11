from __future__ import annotations

import json

import pytest

from coordinator.errors import CoordinatorError, ErrorCode
from coordinator.event_manager import EventManager
from coordinator.service import V2BCoordinator
from tests.helpers import FakeProvider
from v2b_coordinator import parser, print_analysis_result


def build_handoff(project):
    manager = EventManager(project / "schemas" / "event_handoff.schema.json")
    return manager.build_handoff(manager.load_event(project / "samples" / "simulated_event.json"))


@pytest.mark.parametrize("level", ["none", "low", "high", "max"])
def test_analyze_handoff_parser_accepts_supported_reasoning_levels(level):
    args = parser().parse_args([
        "analyze-handoff",
        "--handoff",
        "state/last_simulated_handoff.json",
        "--provider",
        "deepseek",
        "--reasoning",
        level,
    ])
    assert args.reasoning == level


def test_analyze_handoff_parser_rejects_unsupported_reasoning_level():
    with pytest.raises(SystemExit):
        parser().parse_args([
            "analyze-handoff",
            "--handoff",
            "state/last_simulated_handoff.json",
            "--provider",
            "deepseek",
            "--reasoning",
            "abc",
        ])


def test_reasoning_override_reaches_deepseek_provider_config(sandbox_project):
    handoff = build_handoff(sandbox_project)
    captured = {}
    provider = FakeProvider()

    def factory(name, config, prompt, output_schema):
        del prompt, output_schema
        captured.update({"name": name, "config": config})
        return provider

    coordinator = V2BCoordinator(
        sandbox_project,
        provider_factory=factory,
        sleep_fn=lambda _seconds: None,
    )
    result = coordinator.analyze_handoff(
        handoff,
        provider_name="deepseek",
        reasoning_effort="high",
    )

    assert captured["name"] == "deepseek"
    assert captured["config"]["reasoning_effort"] == "high"
    assert result["reasoning_effort"] == "high"
    assert coordinator.config.provider_config("deepseek")["reasoning_effort"] == "none"


def test_reasoning_override_for_non_deepseek_is_rejected(sandbox_project):
    handoff = build_handoff(sandbox_project)
    coordinator = V2BCoordinator(sandbox_project, sleep_fn=lambda _seconds: None)

    with pytest.raises(CoordinatorError) as caught:
        coordinator.analyze_handoff(
            handoff,
            provider_name="openai",
            reasoning_effort="low",
        )

    assert caught.value.code == ErrorCode.CONFIG_ERROR
    assert caught.value.message == "reasoning override is currently supported for deepseek only"
    assert (sandbox_project / "state" / "jobs.jsonl").read_text(encoding="utf-8") == ""


def test_analysis_result_prints_reasoning_effort_and_reasoning_tokens(capsys):
    result = {
        "job": {"status": "RESULT_READY", "job_id": "JOB-1"},
        "decision": {
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "decision_id": "DEC-1",
            "action": "WATCH",
        },
        "usage": [{
            "latency_ms": 10,
            "input_tokens": 20,
            "output_tokens": 30,
            "reasoning_tokens": 12,
            "total_tokens": 50,
        }],
        "reasoning_effort": "high",
    }

    assert print_analysis_result(result) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["reasoning_effort"] == "high"
    assert output["reasoning_tokens"] == 12
