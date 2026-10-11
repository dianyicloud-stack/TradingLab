from __future__ import annotations

import json

import pytest
import yaml

from coordinator.action_policy import (
    ACTION_POLICY_MODES,
    DEFAULT_ACTION_POLICY,
    build_action_policy_prompt,
)
from coordinator.config_manager import ConfigManager
from coordinator.errors import CoordinatorError, ErrorCode
from coordinator.event_manager import EventManager
from coordinator.service import V2BCoordinator
from tests.helpers import FakeProvider, valid_analysis
from v2b_coordinator import parser, print_analysis_result


def build_handoff(project):
    manager = EventManager(project / "schemas" / "event_handoff.schema.json")
    return manager.build_handoff(manager.load_event(project / "samples" / "simulated_event.json"))


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_default_action_policy_and_doctor_report(sandbox_project):
    config = ConfigManager(sandbox_project)
    assert config.action_policy() == DEFAULT_ACTION_POLICY
    assert config.doctor()["action_policy"] == DEFAULT_ACTION_POLICY


@pytest.mark.parametrize(
    "field,value,expected_message",
    [
        ("mode", "unsupported", "action_policy.mode must be one of"),
        ("allow_preemptive_exit", "true", "action_policy.allow_preemptive_exit must be a boolean"),
        ("exit_confidence_floor", -0.01, "action_policy.exit_confidence_floor must be null or a number from 0 to 1"),
        ("exit_confidence_floor", 1.01, "action_policy.exit_confidence_floor must be null or a number from 0 to 1"),
        ("exit_confidence_floor", True, "action_policy.exit_confidence_floor must be null or a number from 0 to 1"),
    ],
)
def test_invalid_action_policy_is_a_config_error(sandbox_project, field, value, expected_message):
    config_path = sandbox_project / "config.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["action_policy"][field] = value
    config_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(CoordinatorError) as caught:
        ConfigManager(sandbox_project)

    assert caught.value.code == ErrorCode.CONFIG_ERROR
    assert expected_message in caught.value.message


@pytest.mark.parametrize("mode", sorted(ACTION_POLICY_MODES))
def test_cli_accepts_each_action_policy(mode):
    args = parser().parse_args([
        "analyze-handoff",
        "--handoff",
        "state/last_simulated_handoff.json",
        "--action-policy",
        mode,
    ])
    assert args.action_policy == mode


def test_cli_rejects_invalid_action_policy():
    with pytest.raises(SystemExit):
        parser().parse_args([
            "analyze-handoff",
            "--handoff",
            "state/last_simulated_handoff.json",
            "--action-policy",
            "unsupported",
        ])


def test_policy_prompts_are_explicit_and_distinct():
    prompts = {}
    for mode in ACTION_POLICY_MODES:
        policy = {**DEFAULT_ACTION_POLICY, "mode": mode}
        prompt = build_action_policy_prompt(policy)
        prompts[mode] = prompt
        assert "ACTION DECISION POLICY" in prompt
        assert f"mode: {mode}" in prompt
        assert "allow_preemptive_exit: true" in prompt
        assert "exit_confidence_floor: null" in prompt
        assert "single indicator" in prompt
        assert "one price drop" in prompt
    assert len(set(prompts.values())) == 3
    assert "support level is breached" in prompts["structure_first"]
    assert "WATCH is usually preferred" in prompts["balanced"]
    assert "Prioritize price confirmation" in prompts["key_level_first"]


@pytest.mark.parametrize("mode", sorted(ACTION_POLICY_MODES))
def test_cli_policy_override_reaches_prompt_result_and_job_without_persisting(sandbox_project, mode):
    captured = {}
    provider = FakeProvider()

    def factory(name, config, prompt, output_schema):
        del name, config, output_schema
        captured["prompt"] = prompt
        return provider

    coordinator = V2BCoordinator(sandbox_project, provider_factory=factory, sleep_fn=lambda _seconds: None)
    result = coordinator.analyze_handoff(
        build_handoff(sandbox_project),
        provider_name="deepseek",
        reasoning_effort="low",
        action_policy_mode=mode,
    )

    assert f"mode: {mode}" in captured["prompt"]
    assert result["action_policy"] == mode
    assert result["reasoning_effort"] == "low"
    assert coordinator.config.action_policy()["mode"] == "structure_first"
    jobs = load_jsonl(sandbox_project / "state" / "jobs.jsonl")
    assert jobs
    assert all(job["action_policy"] == {**DEFAULT_ACTION_POLICY, "mode": mode} for job in jobs)


def test_config_values_are_injected_and_audited(sandbox_project):
    coordinator = V2BCoordinator(
        sandbox_project,
        provider_factory=lambda name, config, prompt, output_schema: FakeProvider(),
        sleep_fn=lambda _seconds: None,
    )
    coordinator.config.data["action_policy"] = {
        "mode": "balanced",
        "allow_preemptive_exit": False,
        "exit_confidence_floor": 0.7,
    }
    captured = {}

    def factory(name, config, prompt, output_schema):
        del name, config, output_schema
        captured["prompt"] = prompt
        return FakeProvider()

    coordinator.provider_factory = factory
    result = coordinator.analyze_handoff(build_handoff(sandbox_project))

    assert result["action_policy"] == "balanced"
    assert "allow_preemptive_exit: false" in captured["prompt"]
    assert "exit_confidence_floor: 0.7" in captured["prompt"]
    assert "Do not use a preemptive EXIT" in captured["prompt"]
    final_job = load_jsonl(sandbox_project / "state" / "jobs.jsonl")[-1]
    assert final_job["action_policy"] == coordinator.config.data["action_policy"]


def test_exit_below_confidence_floor_fails_without_decision_or_action_mutation(sandbox_project):
    handoff = build_handoff(sandbox_project)
    analysis = valid_analysis(handoff, action="EXIT")
    analysis["confidence"] = 0.69
    coordinator = V2BCoordinator(
        sandbox_project,
        provider_factory=lambda name, config, prompt, output_schema: FakeProvider([analysis]),
        sleep_fn=lambda _seconds: None,
    )
    coordinator.config.data["action_policy"]["exit_confidence_floor"] = 0.7

    with pytest.raises(CoordinatorError) as caught:
        coordinator.analyze_handoff(handoff)

    assert caught.value.code == ErrorCode.POLICY_VALIDATION_FAILED
    assert caught.value.message == "EXIT confidence below configured policy floor."
    assert analysis["action"] == "EXIT"
    assert (sandbox_project / "state" / "decisions.jsonl").read_text(encoding="utf-8") == ""
    jobs = load_jsonl(sandbox_project / "state" / "jobs.jsonl")
    assert jobs[-1]["status"] == "FAILED"
    assert jobs[-1]["error_code"] == ErrorCode.POLICY_VALIDATION_FAILED


def test_exit_at_confidence_floor_succeeds(sandbox_project):
    handoff = build_handoff(sandbox_project)
    analysis = valid_analysis(handoff, action="EXIT")
    analysis["confidence"] = 0.7
    coordinator = V2BCoordinator(
        sandbox_project,
        provider_factory=lambda name, config, prompt, output_schema: FakeProvider([analysis]),
        sleep_fn=lambda _seconds: None,
    )
    coordinator.config.data["action_policy"]["exit_confidence_floor"] = 0.7

    result = coordinator.analyze_handoff(handoff)

    assert result["job"]["status"] == "RESULT_READY"
    assert result["decision"]["action"] == "EXIT"
    assert len(load_jsonl(sandbox_project / "state" / "decisions.jsonl")) == 1


def test_non_exit_is_not_blocked_by_exit_confidence_floor(sandbox_project):
    handoff = build_handoff(sandbox_project)
    analysis = valid_analysis(handoff, action="WATCH")
    analysis["confidence"] = 0.2
    coordinator = V2BCoordinator(
        sandbox_project,
        provider_factory=lambda name, config, prompt, output_schema: FakeProvider([analysis]),
        sleep_fn=lambda _seconds: None,
    )
    coordinator.config.data["action_policy"]["exit_confidence_floor"] = 0.7
    assert coordinator.analyze_handoff(handoff)["decision"]["action"] == "WATCH"


def test_analysis_result_prints_action_policy(capsys):
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
        "action_policy": "key_level_first",
    }
    assert print_analysis_result(result) == 0
    assert json.loads(capsys.readouterr().out)["action_policy"] == "key_level_first"
