from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator, FormatChecker

from .errors import CoordinatorError, ErrorCode
from .models import new_handoff_id, now_iso


class EventManager:
    def __init__(self, schema_path: Path, now_provider: Callable[[], str] = now_iso) -> None:
        self.schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(self.schema, format_checker=FormatChecker())
        self.now_provider = now_provider

    @staticmethod
    def load_event(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CoordinatorError(ErrorCode.EVENT_SCHEMA_INVALID, f"Cannot read simulated event: {error}") from error
        if not isinstance(value, dict):
            raise CoordinatorError(ErrorCode.EVENT_SCHEMA_INVALID, "Event input must be a JSON object")
        return value

    def build_handoff(
        self,
        event_input: dict[str, Any],
        *,
        checkpoint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source = deepcopy(event_input)
        handoff = {
            "schema_version": "1.0",
            "handoff_type": "EVENT_INTERRUPT",
            "handoff_id": new_handoff_id(),
            "generated_at": self.now_provider(),
            "tracking_session_id": source.get("tracking_session_id"),
            "symbol": source.get("symbol"),
            "name": source.get("name"),
            "session_date": source.get("session_date"),
            "decision_checkpoint": deepcopy(checkpoint if checkpoint is not None else source.get("decision_checkpoint")),
            "trigger_event": deepcopy(source.get("trigger_event")),
            "composite_event": deepcopy(source.get("composite_event")),
            "events_since_checkpoint": deepcopy(source.get("events_since_checkpoint")),
            "observation_rows_since_checkpoint": deepcopy(source.get("observation_rows_since_checkpoint")),
            "runtime_context": deepcopy(source.get("runtime_context")),
            "current_state": deepcopy(source.get("current_state")),
            "cursor_snapshot": deepcopy(source.get("cursor_snapshot")),
            "metadata": deepcopy(source.get("metadata") or {}),
        }
        self.validate_handoff(handoff)
        return handoff

    def validate_handoff(self, handoff: dict[str, Any]) -> None:
        errors = sorted(self.validator.iter_errors(handoff), key=lambda item: list(item.path))
        if errors:
            first = errors[0]
            path = ".".join(str(part) for part in first.path) or "$"
            raise CoordinatorError(ErrorCode.EVENT_SCHEMA_INVALID, f"Event Handoff schema failed at {path}: {first.message}")
        self.validate_handoff_semantics(handoff)

    @staticmethod
    def _time_minutes(value: str, field: str) -> int:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise CoordinatorError(
                ErrorCode.HANDOFF_SEMANTIC_VALIDATION_FAILED,
                f"{field} is not a valid HH:MM time",
            )
        hour, minute = (int(part) for part in value.split(":"))
        return hour * 60 + minute

    @staticmethod
    def _semantic_failure(message: str) -> None:
        raise CoordinatorError(ErrorCode.HANDOFF_SEMANTIC_VALIDATION_FAILED, message)

    def validate_handoff_semantics(self, handoff: dict[str, Any]) -> None:
        """Validate relationships that JSON Schema cannot express."""
        cursor = handoff["cursor_snapshot"]
        last_event_seq = cursor["last_processed_event_seq"]
        max_event_seq = cursor["handoff_max_event_seq"]
        if last_event_seq is not None and max_event_seq is not None and last_event_seq > max_event_seq:
            self._semantic_failure("last_processed_event_seq exceeds handoff_max_event_seq")

        last_observation_time = cursor["last_processed_observation_time"]
        max_observation_time = cursor["handoff_max_observation_time"]
        if last_observation_time is not None:
            last_observation_minutes = self._time_minutes(
                last_observation_time,
                "cursor_snapshot.last_processed_observation_time",
            )
        else:
            last_observation_minutes = None
        if max_observation_time is not None:
            max_observation_minutes = self._time_minutes(
                max_observation_time,
                "cursor_snapshot.handoff_max_observation_time",
            )
        else:
            max_observation_minutes = None
        if (
            last_observation_minutes is not None
            and max_observation_minutes is not None
            and last_observation_minutes > max_observation_minutes
        ):
            self._semantic_failure("last_processed_observation_time exceeds handoff_max_observation_time")

        tracking_session_id = handoff["tracking_session_id"]
        for field in ("trigger_event", "current_state", "decision_checkpoint"):
            value = handoff.get(field)
            if isinstance(value, dict) and value.get("tracking_session_id") is not None:
                if value["tracking_session_id"] != tracking_session_id:
                    self._semantic_failure(f"{field}.tracking_session_id does not match Event Handoff")

        session_date = handoff["session_date"]
        for field in ("trigger_event", "decision_checkpoint"):
            value = handoff.get(field)
            if isinstance(value, dict) and value.get("session_date") is not None:
                if value["session_date"] != session_date:
                    self._semantic_failure(f"{field}.session_date does not match Event Handoff")

        trigger_event_seq = handoff["trigger_event"].get("event_seq")
        if max_event_seq is not None and trigger_event_seq is not None and max_event_seq < trigger_event_seq:
            self._semantic_failure("handoff_max_event_seq is below trigger_event.event_seq")

        self._validate_observation_completeness(
            handoff["observation_rows_since_checkpoint"],
            last_observation_time=last_observation_time,
            last_observation_minutes=last_observation_minutes,
            max_observation_time=max_observation_time,
            max_observation_minutes=max_observation_minutes,
        )
        self._validate_event_completeness(
            handoff,
            last_event_seq=last_event_seq,
            max_event_seq=max_event_seq,
        )

    def _validate_observation_completeness(
        self,
        rows: list[dict[str, Any]],
        *,
        last_observation_time: str | None,
        last_observation_minutes: int | None,
        max_observation_time: str | None,
        max_observation_minutes: int | None,
    ) -> None:
        if not rows:
            if max_observation_time != last_observation_time:
                self._semantic_failure(
                    "OBSERVATION_CURSOR_GAP: empty observation increment requires frozen max to equal last processed"
                )
            return

        if max_observation_minutes is None:
            self._semantic_failure("OBSERVATION_CURSOR_GAP: non-empty observation increment requires a frozen max")

        requested_minutes = [
            self._time_minutes(
                row["requested_time"],
                f"observation_rows_since_checkpoint[{index}].requested_time",
            )
            for index, row in enumerate(rows)
        ]
        if len(set(requested_minutes)) != len(requested_minutes):
            self._semantic_failure("OBSERVATION_DUPLICATE_TIME: requested_time values must be unique")
        if requested_minutes != sorted(requested_minutes):
            self._semantic_failure("OBSERVATION_OUT_OF_ORDER: requested_time values must be strictly ascending")
        if last_observation_minutes is not None and any(
            value <= last_observation_minutes for value in requested_minutes
        ):
            self._semantic_failure(
                "OBSERVATION_NOT_INCREMENTAL: requested_time must be later than last processed observation"
            )
        if max(requested_minutes) != max_observation_minutes:
            self._semantic_failure(
                "OBSERVATION_CURSOR_GAP: frozen observation max must equal the latest included observation"
            )

    def _validate_event_completeness(
        self,
        handoff: dict[str, Any],
        *,
        last_event_seq: int | None,
        max_event_seq: int | None,
    ) -> None:
        events = handoff["events_since_checkpoint"]
        actual = [event["event_seq"] for event in events]
        if len(set(actual)) != len(actual):
            self._semantic_failure("EVENT_DUPLICATE_SEQ: event_seq values must be unique")
        if actual != sorted(actual):
            self._semantic_failure("EVENT_OUT_OF_ORDER: event_seq values must be strictly ascending")

        if not events:
            if max_event_seq != last_event_seq:
                self._semantic_failure(
                    "EVENT_CURSOR_GAP: empty event increment requires frozen max to equal last processed"
                )
        else:
            if max_event_seq is None:
                self._semantic_failure("EVENT_CURSOR_GAP: non-empty event increment requires a frozen max")
            first_expected = 1 if last_event_seq is None else last_event_seq + 1
            expected = list(range(first_expected, max_event_seq + 1))
            if actual != expected:
                self._semantic_failure(
                    f"EVENT_CURSOR_GAP: expected event_seq {expected}, received {actual}"
                )

        trigger_event_seq = handoff["trigger_event"]["event_seq"]
        trigger_is_incremental = last_event_seq is None or trigger_event_seq > last_event_seq
        if trigger_is_incremental and trigger_event_seq not in actual:
            self._semantic_failure("TRIGGER_EVENT_NOT_INCLUDED: trigger_event is absent from event increment")

        event_ids = {event["event_id"] for event in events}
        composite = handoff.get("composite_event")
        if isinstance(composite, dict):
            for reference_field in ("source_event_ids", "member_event_ids"):
                if reference_field not in composite:
                    continue
                references = composite[reference_field]
                if not isinstance(references, list) or not all(isinstance(item, str) for item in references):
                    self._semantic_failure(
                        f"COMPOSITE_EVENT_SOURCE_MISSING: {reference_field} must be an event ID array"
                    )
                missing = [event_id for event_id in references if event_id not in event_ids]
                if missing:
                    self._semantic_failure(
                        f"COMPOSITE_EVENT_SOURCE_MISSING: referenced events are absent: {missing}"
                    )
