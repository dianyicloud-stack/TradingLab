from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import now_iso
from .storage import JsonlStore


class UsageManager:
    def __init__(self, path: Path) -> None:
        self.store = JsonlStore(path)

    @staticmethod
    def calculate_cost(usage: dict[str, Any], pricing: dict[str, Any]) -> float | None:
        input_rate = pricing.get("input_per_million")
        cached_rate = pricing.get("cached_input_per_million")
        output_rate = pricing.get("output_per_million")
        if input_rate is None or output_rate is None:
            return None
        cached = int(usage.get("cached_input_tokens") or 0)
        if cached > 0 and cached_rate is None:
            return None
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        uncached = max(0, input_tokens - cached)
        cost = (
            uncached * float(input_rate)
            + cached * float(cached_rate or 0)
            + output_tokens * float(output_rate)
        ) / 1_000_000
        return round(cost, 10)

    def record(
        self,
        *,
        job: dict[str, Any],
        handoff: dict[str, Any],
        provider: str,
        model: str,
        attempt: int,
        usage: dict[str, Any],
        pricing: dict[str, Any],
    ) -> dict[str, Any]:
        allowed = {
            "request_id", "latency_ms", "input_tokens", "output_tokens", "total_tokens",
            "cached_input_tokens", "reasoning_tokens", "success", "error_type", "structured_output", "fallback_used",
        }
        safe_usage = {key: usage.get(key) for key in allowed}
        record = {
            "timestamp": now_iso(),
            "job_id": job["job_id"],
            "handoff_id": handoff["handoff_id"],
            "provider": provider,
            "model": model,
            "attempt": attempt,
            **safe_usage,
        }
        record["cost_usd"] = self.calculate_cost(record, pricing)
        self.store.append(record)
        return record
