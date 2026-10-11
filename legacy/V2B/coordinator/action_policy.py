from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Mapping

from .errors import CoordinatorError, ErrorCode


ACTION_POLICY_MODES = {"structure_first", "balanced", "key_level_first"}

DEFAULT_ACTION_POLICY: dict[str, Any] = {
    "mode": "structure_first",
    "allow_preemptive_exit": True,
    "exit_confidence_floor": None,
}

_MODE_INSTRUCTIONS = {
    "structure_first": (
        "Use structure-first decision logic. Structural invalidation or sustained supply-side control may justify EXIT "
        "before the main support level is breached when preemptive exits are allowed. Treat key support as an important "
        "reference, not an absolute prerequisite. A single indicator deterioration or a single price drop is insufficient "
        "by itself; assess the combined market structure and evidence."
    ),
    "balanced": (
        "Require a balance of structural evidence and price confirmation. When structure deteriorates but the main key "
        "level remains intact, WATCH is usually preferred. Upgrade to EXIT only when invalidation becomes stronger, a key "
        "level is breached, or the evidence disproves buyer acceptance. A single indicator deterioration or a single "
        "price drop is insufficient by itself."
    ),
    "key_level_first": (
        "Prioritize price confirmation at key levels. Significant VWAP, Alpha, or price-efficiency deterioration while "
        "main support remains intact should usually result in WATCH. Use EXIT only after the main support is breached or "
        "an equivalently strong structural break is established. A single indicator deterioration or a single price "
        "drop is insufficient by itself."
    ),
}


def validate_action_policy(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return deepcopy(DEFAULT_ACTION_POLICY)
    if not isinstance(value, Mapping):
        raise CoordinatorError(ErrorCode.CONFIG_ERROR, "action_policy must be a mapping")

    policy = deepcopy(DEFAULT_ACTION_POLICY)
    policy.update(dict(value))

    mode = policy.get("mode")
    if not isinstance(mode, str) or mode not in ACTION_POLICY_MODES:
        allowed = ", ".join(sorted(ACTION_POLICY_MODES))
        raise CoordinatorError(ErrorCode.CONFIG_ERROR, f"action_policy.mode must be one of: {allowed}")

    allow_preemptive_exit = policy.get("allow_preemptive_exit")
    if type(allow_preemptive_exit) is not bool:
        raise CoordinatorError(ErrorCode.CONFIG_ERROR, "action_policy.allow_preemptive_exit must be a boolean")

    floor = policy.get("exit_confidence_floor")
    if floor is not None:
        if isinstance(floor, bool) or not isinstance(floor, (int, float)) or not math.isfinite(float(floor)):
            raise CoordinatorError(
                ErrorCode.CONFIG_ERROR,
                "action_policy.exit_confidence_floor must be null or a number from 0 to 1",
            )
        if not 0 <= float(floor) <= 1:
            raise CoordinatorError(
                ErrorCode.CONFIG_ERROR,
                "action_policy.exit_confidence_floor must be null or a number from 0 to 1",
            )
        policy["exit_confidence_floor"] = float(floor)

    return policy


def resolve_action_policy(
    configured: Mapping[str, Any] | None,
    mode_override: str | None = None,
) -> dict[str, Any]:
    policy = validate_action_policy(configured)
    if mode_override is not None:
        policy["mode"] = mode_override
    return validate_action_policy(policy)


def build_action_policy_prompt(policy: Mapping[str, Any]) -> str:
    resolved = validate_action_policy(policy)
    floor = resolved["exit_confidence_floor"]
    floor_text = "null" if floor is None else str(floor)
    preemptive_instruction = (
        "Preemptive EXIT before the main support breach is allowed when the active policy's structural conditions are met."
        if resolved["allow_preemptive_exit"]
        else "Do not use a preemptive EXIT before the main support is lost; normally use WATCH instead, except for already-defined CRITICAL risks."
    )
    confidence_instruction = (
        "No coordinator-level EXIT confidence floor is configured."
        if floor is None
        else f"Any EXIT decision must have confidence greater than or equal to {floor_text}."
    )
    return "\n".join((
        "ACTION DECISION POLICY",
        f"mode: {resolved['mode']}",
        f"allow_preemptive_exit: {str(resolved['allow_preemptive_exit']).lower()}",
        f"exit_confidence_floor: {floor_text}",
        "Apply this policy to the existing Decision action field without adding indicators, thresholds, or schema fields.",
        _MODE_INSTRUCTIONS[resolved["mode"]],
        preemptive_instruction,
        confidence_instruction,
        "Judge the overall structural status from the supplied evidence; never base EXIT on one threshold, one indicator, or one price drop alone.",
    ))


def validate_decision_policy(decision: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    resolved = validate_action_policy(policy)
    floor = resolved["exit_confidence_floor"]
    if decision.get("action") != "EXIT" or floor is None:
        return
    confidence = decision.get("confidence")
    if confidence is None or isinstance(confidence, bool) or float(confidence) < floor:
        raise CoordinatorError(
            ErrorCode.POLICY_VALIDATION_FAILED,
            "EXIT confidence below configured policy floor.",
        )
