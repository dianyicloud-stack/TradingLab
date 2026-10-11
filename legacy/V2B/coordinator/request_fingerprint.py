from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def build_request_fingerprint(
    *,
    handoff: Mapping[str, Any],
    provider: str,
    model: str,
    reasoning_effort: str | None,
    action_policy: Mapping[str, Any],
    effective_prompt: str,
    decision_schema: Mapping[str, Any],
    provider_output_schema: Mapping[str, Any],
    provider_request_options: Mapping[str, Any] | None = None,
) -> str:
    payload = {
        "handoff": handoff,
        "provider": provider,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "action_policy": action_policy,
        "prompt_sha256": hashlib.sha256(effective_prompt.encode("utf-8")).hexdigest(),
        "decision_schema_sha256": sha256_json(decision_schema),
        "provider_output_schema_sha256": sha256_json(provider_output_schema),
        "provider_request_options": dict(provider_request_options or {}),
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
