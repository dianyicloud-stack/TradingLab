from __future__ import annotations

from typing import Any

from coordinator.errors import CoordinatorError, ErrorCode
from providers.base import AIProvider


def valid_analysis(handoff: dict[str, Any], *, action: str = "WATCH") -> dict[str, Any]:
    return {
        "market_state": "偏弱",
        "structure_state": "Alpha恶化且价格位于VWAP下方",
        "action": action,
        "key_levels": {"support": 24.6, "reference": 24.93, "resistance": 25.2},
        "invalidation": "重新站稳25.20且Alpha恢复",
        "reason_summary": ["Alpha快速恶化", "行业宽度为正但个股相对走弱"],
        "confidence": 0.78,
    }


def usage_record(*, success: bool, error_type: str | None = None) -> dict[str, Any]:
    return {
        "request_id": "req_mock",
        "latency_ms": 12.5,
        "input_tokens": 500 if success else None,
        "output_tokens": 120 if success else None,
        "total_tokens": 620 if success else None,
        "cached_input_tokens": 50 if success else None,
        "success": success,
        "error_type": error_type,
        "structured_output": True,
        "fallback_used": False,
    }


def provider_error(code: ErrorCode, *, retryable: bool, message: str | None = None) -> CoordinatorError:
    return CoordinatorError(
        code,
        message or f"mock {code.value}",
        retryable=retryable,
        usage_records=[usage_record(success=False, error_type=code.value)],
    )


class FakeProvider(AIProvider):
    name = "openai"
    model = "mock-model"

    def __init__(self, outcomes: list[object] | None = None) -> None:
        self.outcomes = list(outcomes or [None])
        self.calls = 0

    def analyze_event(
        self,
        handoff: dict[str, Any],
        *,
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del request_context
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        analysis = outcome if isinstance(outcome, dict) else valid_analysis(handoff)
        return {
            "analysis": analysis,
            "usage_records": [usage_record(success=True)],
            "request_id": "req_mock",
            "structured_output": True,
            "fallback_used": False,
        }


def fake_factory(provider: FakeProvider):
    return lambda name, config, prompt, output_schema: provider
