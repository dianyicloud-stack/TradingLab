from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from coordinator.service import V2BCoordinator


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def deepseek_integration_result(tmp_path_factory):
    if not os.getenv("DEEPSEEK_API_KEY"):
        pytest.skip("SKIPPED: DEEPSEEK_API_KEY not configured")
    source_root = Path(__file__).resolve().parents[1]
    target = tmp_path_factory.mktemp("deepseek_integration")
    for relative in (
        "config.yaml",
        "schemas/event_handoff.schema.json",
        "schemas/decision.schema.json",
        "prompts/market_analysis_prompt.txt",
        "samples/simulated_event.json",
    ):
        source = source_root / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    (target / "state").mkdir()
    (target / "logs").mkdir()
    result = V2BCoordinator(target).analyze(target / "samples" / "simulated_event.json")
    usage = result["usage"][-1]
    print(json.dumps({
        "provider": result["decision"]["provider"],
        "model": result["decision"]["model"],
        "latency_ms": usage.get("latency_ms"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cached_input_tokens": usage.get("cached_input_tokens"),
        "reasoning_tokens": usage.get("reasoning_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "decision_id": result["decision"]["decision_id"],
        "action": result["decision"]["action"],
    }, ensure_ascii=False, indent=2))
    return result


def test_real_deepseek_responses_api(deepseek_integration_result):
    assert deepseek_integration_result["job"]["status"] == "RESULT_READY"
    assert deepseek_integration_result["decision"]["provider"] == "deepseek"
    assert deepseek_integration_result["decision"]["model"] == "deepseek-v4-pro"


def test_real_deepseek_decision_schema_and_system_cursors(deepseek_integration_result):
    decision = deepseek_integration_result["decision"]
    cursor = deepseek_integration_result["handoff"]["cursor_snapshot"]
    assert decision["action"] in {"HOLD", "WATCH", "EXIT", "NO_ACTION"}
    assert decision["processed_through_seq"] == cursor["handoff_max_event_seq"]
    assert decision["processed_through_observation_time"] == cursor["handoff_max_observation_time"]


def test_real_deepseek_usage_is_logged_without_static_cost(deepseek_integration_result):
    usage = deepseek_integration_result["usage"][-1]
    assert usage["input_tokens"] is not None
    assert usage["output_tokens"] is not None
    assert usage["total_tokens"] is not None
    assert usage["cost_usd"] is None
