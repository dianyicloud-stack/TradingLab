from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .errors import CoordinatorError, ErrorCode
from .models import new_decision_id, now_iso


ANALYSIS_FIELDS = (
    "market_state",
    "structure_state",
    "action",
    "key_levels",
    "invalidation",
    "reason_summary",
    "confidence",
)

STRUCTURED_OUTPUT_UNSUPPORTED_KEYWORDS = {
    "$schema", "$id", "format", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "multipleOf", "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems",
}


def structured_output_compatible_schema(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: structured_output_compatible_schema(item)
            for key, item in value.items()
            if key not in STRUCTURED_OUTPUT_UNSUPPORTED_KEYWORDS
        }
    if isinstance(value, list):
        return [structured_output_compatible_schema(item) for item in value]
    return value


class DecisionManager:
    def __init__(self, schema_path: Path) -> None:
        self.schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema, format_checker=FormatChecker())

    def analysis_schema(self) -> dict[str, Any]:
        properties = self.schema["properties"]
        return {
            "type": "object",
            "additionalProperties": False,
            "required": list(ANALYSIS_FIELDS),
            "properties": {field: deepcopy(properties[field]) for field in ANALYSIS_FIELDS},
        }

    def provider_output_schema(self) -> dict[str, Any]:
        return structured_output_compatible_schema(self.analysis_schema())

    def build_decision(
        self,
        analysis: dict[str, Any],
        *,
        handoff: dict[str, Any],
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        if not isinstance(analysis, dict):
            raise CoordinatorError(ErrorCode.INVALID_RESPONSE, "Provider analysis must be a JSON object")
        decision = {
            "schema_version": "1.0",
            "decision_id": new_decision_id(),
            "provider": provider,
            "model": model,
            "handoff_id": handoff["handoff_id"],
            "tracking_session_id": handoff["tracking_session_id"],
            "symbol": handoff["symbol"],
            "analyzed_at": now_iso(),
        }
        decision.update({field: analysis.get(field) for field in ANALYSIS_FIELDS})
        cursor = handoff["cursor_snapshot"]
        decision["processed_through_seq"] = cursor["handoff_max_event_seq"]
        decision["processed_through_observation_time"] = cursor["handoff_max_observation_time"]
        self.validate_decision(decision, handoff)
        return decision

    def validate_decision(self, decision: dict[str, Any], handoff: dict[str, Any]) -> None:
        errors = sorted(self.validator.iter_errors(decision), key=lambda item: list(item.path))
        if errors:
            first = errors[0]
            path = ".".join(str(part) for part in first.path) or "$"
            raise CoordinatorError(ErrorCode.SCHEMA_VALIDATION_FAILED, f"Decision schema failed at {path}: {first.message}")
        for field in ("handoff_id", "tracking_session_id", "symbol"):
            if decision[field] != handoff[field]:
                raise CoordinatorError(ErrorCode.SCHEMA_VALIDATION_FAILED, f"Decision {field} does not match Event Handoff")
        cursor = handoff["cursor_snapshot"]
        if decision["processed_through_seq"] != cursor["handoff_max_event_seq"]:
            raise CoordinatorError(ErrorCode.SCHEMA_VALIDATION_FAILED, "processed_through_seq does not equal frozen cursor")
        if decision["processed_through_observation_time"] != cursor["handoff_max_observation_time"]:
            raise CoordinatorError(
                ErrorCode.SCHEMA_VALIDATION_FAILED,
                "processed_through_observation_time does not equal frozen cursor",
            )
