from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import openai
from openai import OpenAI

from coordinator.errors import CoordinatorError, ErrorCode, safe_error_message
from coordinator.config_manager import DEEPSEEK_REASONING_EFFORTS

from .base import AIProvider


DEEPSEEK_API_TYPE = "responses"
EMPTY_RESPONSE_MAX_ATTEMPTS = 3
DEEPSEEK_JSON_INSTRUCTIONS = """

JSON output requirements:
Return exactly one valid JSON object.
Do not output Markdown.
Do not output code fences.
Do not output commentary before or after the JSON.
Do not add fields not defined by the schema.
The response MUST satisfy the supplied Decision Schema.
Use exactly the existing Decision analysis fields required by the supplied JSON Schema.
""".rstrip()


@dataclass
class _CallFailure(Exception):
    cause: Exception
    usage_record: dict[str, Any]


class DeepSeekProvider(AIProvider):
    name = "deepseek"

    def __init__(
        self,
        config: dict[str, Any],
        *,
        prompt: str,
        output_schema: dict[str, Any],
        client: Any | None = None,
    ) -> None:
        self.config = dict(config)
        self.model = str(config.get("model") or "").strip()
        if not self.model:
            raise CoordinatorError(ErrorCode.CONFIG_ERROR, "DeepSeek model is not configured")
        self.api_key_env = str(config.get("api_key_env") or "DEEPSEEK_API_KEY")
        self.api_key = os.getenv(self.api_key_env, "").strip()
        if not self.api_key:
            raise CoordinatorError(ErrorCode.API_KEY_MISSING, f"{self.api_key_env} is not configured")
        self.base_url = str(config.get("base_url") or "https://api.deepseek.com").rstrip("/")
        self.timeout_seconds = float(config.get("timeout_seconds") or 90)
        configured_max_output_tokens = config.get("max_output_tokens")
        if configured_max_output_tokens is not None and (
            isinstance(configured_max_output_tokens, bool)
            or not isinstance(configured_max_output_tokens, int)
            or configured_max_output_tokens <= 0
        ):
            raise CoordinatorError(
                ErrorCode.CONFIG_ERROR,
                "DeepSeek max_output_tokens must be null or a positive integer",
            )
        self.max_output_tokens = configured_max_output_tokens
        self.structured_outputs = bool(config.get("structured_outputs", True))
        self.allow_json_fallback = bool(config.get("allow_json_fallback", True))
        self.reasoning_effort = config.get("reasoning_effort", "none")
        if self.reasoning_effort not in DEEPSEEK_REASONING_EFFORTS:
            allowed = ", ".join(sorted(DEEPSEEK_REASONING_EFFORTS))
            raise CoordinatorError(
                ErrorCode.CONFIG_ERROR,
                f"DeepSeek reasoning_effort must be one of: {allowed}",
            )
        self.prompt = prompt
        self.output_schema = output_schema
        self.decision_validation_schema: dict[str, Any] = {}
        self.client = client or OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            max_retries=0,
        )

    @staticmethod
    def _usage(response: Any) -> dict[str, int | None]:
        usage = getattr(response, "usage", None)
        input_details = getattr(usage, "input_tokens_details", None)
        output_details = getattr(usage, "output_tokens_details", None)
        return {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
            "cached_input_tokens": getattr(input_details, "cached_tokens", None),
            "reasoning_tokens": getattr(output_details, "reasoning_tokens", None),
        }

    def configure_decision_schema(self, schema: dict[str, Any]) -> None:
        self.decision_validation_schema = deepcopy(schema)

    def _schema_constraint_instructions(self) -> str:
        reason_schema = (
            self.decision_validation_schema.get("properties", {}).get("reason_summary", {})
        )
        lines: list[str] = []
        max_items = reason_schema.get("maxItems")
        item_schema = reason_schema.get("items") or {}
        max_length = item_schema.get("maxLength") if isinstance(item_schema, dict) else None
        if isinstance(max_items, int):
            lines.append(f"reason_summary must contain no more than {max_items} items.")
        if isinstance(max_length, int):
            lines.append(
                f"Each reason_summary item must contain no more than {max_length} characters."
            )
        return "\n".join(lines)

    def _generation_instructions(self) -> str:
        constraints = self._schema_constraint_instructions()
        return self.prompt + DEEPSEEK_JSON_INSTRUCTIONS + (f"\n{constraints}" if constraints else "")

    def _call(
        self,
        handoff: dict[str, Any],
        *,
        structured: bool,
        instructions: str | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        started = time.perf_counter()
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions or self._generation_instructions(),
            "input": json.dumps(handoff, ensure_ascii=False),
            "reasoning": {
                "effort": self.reasoning_effort,
            },
        }
        if self.max_output_tokens is not None:
            request["max_output_tokens"] = self.max_output_tokens
        if structured:
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "v2b_market_event_decision",
                    "schema": self.output_schema,
                }
            }
        else:
            request["text"] = {"format": {"type": "json_object"}}
        try:
            response = self.client.responses.create(**request)
        except Exception as error:
            latency_ms = round((time.perf_counter() - started) * 1000, 3)
            record = {
                "request_id": getattr(error, "request_id", None),
                "latency_ms": latency_ms,
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "cached_input_tokens": None,
                "reasoning_tokens": None,
                "success": False,
                "error_type": type(error).__name__,
                "structured_output": structured,
                "fallback_used": not structured,
            }
            raise _CallFailure(error, record) from error
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        record = {
            "request_id": getattr(response, "_request_id", None) or getattr(response, "id", None),
            "latency_ms": latency_ms,
            **self._usage(response),
            "success": True,
            "error_type": None,
            "structured_output": structured,
            "fallback_used": not structured,
        }
        return response, record

    @staticmethod
    def _structured_unavailable(error: Exception) -> bool:
        status = getattr(error, "status_code", None)
        message = str(error).lower()
        format_related = any(
            token in message
            for token in ("json_schema", "structured output", "text.format", "response format", "response_format")
        )
        unavailable = any(
            token in message
            for token in ("unsupported", "not support", "invalid parameter", "unknown parameter")
        )
        return status == 400 and format_related and unavailable

    def _map_error(self, error: Exception, records: list[dict[str, Any]]) -> CoordinatorError:
        status = getattr(error, "status_code", None)
        message = safe_error_message(error, (self.api_key,))
        if isinstance(error, openai.AuthenticationError) or status == 401:
            return CoordinatorError(ErrorCode.AUTH_FAILED, message, status_code=status, usage_records=records)
        if isinstance(error, openai.RateLimitError) or status == 429:
            return CoordinatorError(
                ErrorCode.RATE_LIMITED,
                message,
                retryable=True,
                status_code=status,
                usage_records=records,
            )
        if isinstance(error, openai.APITimeoutError):
            return CoordinatorError(ErrorCode.TIMEOUT, message, retryable=True, usage_records=records)
        if isinstance(error, openai.APIConnectionError):
            return CoordinatorError(ErrorCode.PROVIDER_ERROR, message, retryable=True, usage_records=records)
        if status is not None and status >= 500:
            return CoordinatorError(
                ErrorCode.PROVIDER_ERROR,
                message,
                retryable=True,
                status_code=status,
                usage_records=records,
            )
        if status in (400, 404) and "model" in message.lower():
            return CoordinatorError(ErrorCode.MODEL_INVALID, message, status_code=status, usage_records=records)
        return CoordinatorError(ErrorCode.PROVIDER_ERROR, message, status_code=status, usage_records=records)

    @staticmethod
    def _extract_raw_text(response: Any) -> Any:
        return getattr(response, "output_text", None)

    @staticmethod
    def _response_diagnostics(response: Any) -> tuple[str, str]:
        status = getattr(response, "status", None)
        incomplete_details = getattr(response, "incomplete_details", None)
        finish_reason = getattr(incomplete_details, "reason", None)
        if finish_reason is None:
            finish_reason = getattr(response, "finish_reason", None)
        if status is None:
            for item in getattr(response, "output", None) or []:
                item_status = getattr(item, "status", None)
                if item_status:
                    status = item_status
                    break
        return str(status or "unknown"), str(finish_reason or "unknown")

    def _safe_raw_preview(self, raw_text: Any) -> str:
        preview = str(raw_text)[:200].replace("\r", "\\r").replace("\n", "\\n")
        return safe_error_message(preview, (self.api_key,))

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Provider output must be a JSON object")
        return parsed

    def _request_response(
        self,
        handoff: dict[str, Any],
        *,
        structured: bool,
        records: list[dict[str, Any]],
        instructions: str | None = None,
    ) -> tuple[Any, bool]:
        try:
            response, usage = self._call(
                handoff,
                structured=structured,
                instructions=instructions,
            )
            records.append(usage)
            return response, structured
        except _CallFailure as failure:
            records.append(failure.usage_record)
            if structured and self.allow_json_fallback and self._structured_unavailable(failure.cause):
                records[-1]["error_type"] = "STRUCTURED_OUTPUT_UNAVAILABLE"
                try:
                    response, usage = self._call(
                        handoff,
                        structured=False,
                        instructions=instructions,
                    )
                    records.append(usage)
                    return response, False
                except _CallFailure as fallback_failure:
                    records.append(fallback_failure.usage_record)
                    raise self._map_error(fallback_failure.cause, records) from fallback_failure.cause
            raise self._map_error(failure.cause, records) from failure.cause

    def repair_analysis(
        self,
        original_analysis: dict[str, Any],
        *,
        validator_error: str,
    ) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        repair_instructions = self._generation_instructions() + """

Schema repair task:
Repair the JSON only.
Preserve the analytical conclusion.
Do not introduce new analysis.
Return exactly one valid JSON object conforming to the schema.
""".rstrip()
        repair_payload = {
            "original_decision_json": original_analysis,
            "validator_error": validator_error,
            "decision_schema": self.decision_validation_schema,
        }
        response, structured = self._request_response(
            repair_payload,
            structured=self.structured_outputs,
            records=records,
            instructions=repair_instructions,
        )
        raw_text = self._extract_raw_text(response)
        status, finish_reason = self._response_diagnostics(response)
        if raw_text is None or not str(raw_text).strip():
            records[-1]["success"] = False
            records[-1]["error_type"] = ErrorCode.EMPTY_PROVIDER_RESPONSE.value
            raise CoordinatorError(
                ErrorCode.EMPTY_PROVIDER_RESPONSE,
                (
                    f"provider={self.name} model={self.model} attempts=1 "
                    f"api_type={DEEPSEEK_API_TYPE} response_status={status} "
                    f"finish_reason={finish_reason} raw_content_length=0"
                ),
                usage_records=records,
            )
        raw_text = str(raw_text).strip()
        try:
            analysis = self._parse_json(raw_text)
        except (json.JSONDecodeError, ValueError) as error:
            records[-1]["success"] = False
            records[-1]["error_type"] = ErrorCode.INVALID_RESPONSE.value
            raise CoordinatorError(
                ErrorCode.INVALID_RESPONSE,
                (
                    f"provider={self.name} model={self.model} api_type={DEEPSEEK_API_TYPE} "
                    f"raw_content_length={len(raw_text)} raw_preview={self._safe_raw_preview(raw_text)!r} "
                    f"response_status={status} finish_reason={finish_reason} "
                    f"parse_error={safe_error_message(error)}"
                ),
                usage_records=records,
            ) from error
        return {
            "analysis": analysis,
            "usage_records": records,
            "request_id": records[-1].get("request_id"),
            "structured_output": structured,
            "fallback_used": not structured,
        }

    def analyze_event(
        self,
        handoff: dict[str, Any],
        *,
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del request_context
        records: list[dict[str, Any]] = []
        structured = self.structured_outputs
        analysis: dict[str, Any] | None = None
        for empty_attempt in range(1, EMPTY_RESPONSE_MAX_ATTEMPTS + 1):
            response, structured = self._request_response(
                handoff,
                structured=structured,
                records=records,
            )
            raw_text = self._extract_raw_text(response)
            status, finish_reason = self._response_diagnostics(response)
            if raw_text is None or not str(raw_text).strip():
                records[-1]["success"] = False
                records[-1]["error_type"] = ErrorCode.EMPTY_PROVIDER_RESPONSE.value
                if empty_attempt < EMPTY_RESPONSE_MAX_ATTEMPTS:
                    continue
                raise CoordinatorError(
                    ErrorCode.EMPTY_PROVIDER_RESPONSE,
                    (
                        f"provider={self.name} model={self.model} attempts={empty_attempt} "
                        f"api_type={DEEPSEEK_API_TYPE} response_status={status} "
                        f"finish_reason={finish_reason} raw_content_length=0"
                    ),
                    usage_records=records,
                )
            raw_text = str(raw_text).strip()
            try:
                analysis = self._parse_json(raw_text)
            except (json.JSONDecodeError, ValueError) as error:
                records[-1]["success"] = False
                records[-1]["error_type"] = ErrorCode.INVALID_RESPONSE.value
                raise CoordinatorError(
                    ErrorCode.INVALID_RESPONSE,
                    (
                        f"provider={self.name} model={self.model} api_type={DEEPSEEK_API_TYPE} "
                        f"raw_content_length={len(raw_text)} raw_preview={self._safe_raw_preview(raw_text)!r} "
                        f"response_status={status} finish_reason={finish_reason} "
                        f"parse_error={safe_error_message(error)}"
                    ),
                    usage_records=records,
                ) from error
            break
        if analysis is None:
            raise AssertionError("DeepSeek response loop ended without analysis")
        return {
            "analysis": analysis,
            "usage_records": records,
            "request_id": records[-1].get("request_id"),
            "structured_output": structured,
            "fallback_used": not structured,
        }
