from __future__ import annotations

import os
import json

import pytest

from coordinator.service import V2BCoordinator


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def integration_result(tmp_path_factory):
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("SKIPPED: OPENAI_API_KEY not configured")
    source_root = __import__("pathlib").Path(__file__).resolve().parents[1]
    target = tmp_path_factory.mktemp("openai_integration")
    import shutil

    for relative in (
        "config.yaml", "schemas/event_handoff.schema.json", "schemas/decision.schema.json",
        "prompts/market_analysis_prompt.txt", "samples/simulated_event.json",
    ):
        source = source_root / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    (target / "state").mkdir()
    (target / "logs").mkdir()
    result = V2BCoordinator(target, session_provider="openai").analyze(
        target / "samples" / "simulated_event.json"
    )
    usage = result["usage"][-1]
    print(json.dumps({
        "Provider": result["decision"]["provider"],
        "Model": result["decision"]["model"],
        "Latency": usage.get("latency_ms"),
        "Input tokens": usage.get("input_tokens"),
        "Output tokens": usage.get("output_tokens"),
        "Total tokens": usage.get("total_tokens"),
        "Decision ID": result["decision"]["decision_id"],
        "Action": result["decision"]["action"],
        "Schema": "PASS",
    }, ensure_ascii=False, indent=2))
    return result


def test_t21_real_responses_api(integration_result):
    assert integration_result["job"]["status"] == "RESULT_READY"
    assert integration_result["decision"]["provider"] == "openai"


def test_t22_real_structured_decision(integration_result):
    assert integration_result["decision"]["action"] in {"HOLD", "WATCH", "EXIT", "NO_ACTION"}
    assert integration_result["decision"]["handoff_id"] == integration_result["handoff"]["handoff_id"]


def test_t23_real_token_usage(integration_result):
    usage = integration_result["usage"][-1]
    assert usage["input_tokens"] is not None
    assert usage["output_tokens"] is not None
    assert usage["total_tokens"] is not None
