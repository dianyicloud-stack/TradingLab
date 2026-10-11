from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import openai
from openai import OpenAI

from coordinator.errors import CoordinatorError, ErrorCode, safe_error_message

from .base import AIProvider


@dataclass
class _CallFailure(Exception):
    cause: Exception
    usage_record: dict[str, Any]


class OpenAIProvider(AIProvider):
    name = "openai"

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
            raise CoordinatorError(ErrorCode.CONFIG_ERROR, "OpenAI model is not configured")
        self.api_key_env = str(config.get("api_key_env") or "OPENAI_API_KEY")
        self.api_key = os.getenv(self.api_key_env, "").strip()
        if not self.api_key:
            raise CoordinatorError(ErrorCode.API_KEY_MISSING, f"{self.api_key_env} is not configured")
        self.timeout_seconds = float(config.get("timeout_seconds") or 60)
        self.max_output_tokens = int(config.get("max_output_tokens") or 1600)
        self.structured_outputs = bool(config.get("structured_outputs", True))
        self.allow_json_fallback = bool(config.get("allow_json_fallback", True))
        self.prompt = prompt
        self.output_schema = output_schema
        self.client = client or OpenAI(api_key=self.api_key, timeout=self.timeout_seconds, max_retries=0)

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

    def _call(self, handoff: dict[str, Any], *, structured: bool) -> tuple[Any, dict[str, Any]]:
        started = time.perf_counter()
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": self.prompt if structured else self.prompt + "\n只输出一个JSON对象，不要使用Markdown代码块。",
            "input": json.dumps(handoff, ensure_ascii=False),
            "max_output_tokens": self.max_output_tokens,
            "store": False,
        }
        if structured:
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "v2b_market_event_decision",
                    "strict": True,
                    "schema": self.output_schema,
                }
            }
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
        format_related = any(token in message for token in ("json_schema", "structured output", "text.format", "response format", "response_format"))
        unavailable = any(token in message for token in ("unsupported", "not support", "invalid parameter", "unknown parameter"))
        return status == 400 and format_related and unavailable

    def _map_error(self, error: Exception, records: list[dict[str, Any]]) -> CoordinatorError:
        status = getattr(error, "status_code", None)
        message = safe_error_message(error, (self.api_key,))
        if isinstance(error, openai.AuthenticationError) or status == 401:
            return CoordinatorError(ErrorCode.AUTH_FAILED, message, status_code=status, usage_records=records)
        if isinstance(error, openai.RateLimitError) or status == 429:
            return CoordinatorError(ErrorCode.RATE_LIMITED, message, retryable=True, status_code=status, usage_records=records)
        if isinstance(error, openai.APITimeoutError):
            return CoordinatorError(ErrorCode.TIMEOUT, message, retryable=True, usage_records=records)
        if isinstance(error, openai.APIConnectionError):
            return CoordinatorError(ErrorCode.PROVIDER_ERROR, message, retryable=True, usage_records=records)
        if status is not None and status >= 500:
            return CoordinatorError(ErrorCode.PROVIDER_ERROR, message, retryable=True, status_code=status, usage_records=records)
        if status in (400, 404) and "model" in message.lower():
            return CoordinatorError(ErrorCode.MODEL_INVALID, message, status_code=status, usage_records=records)
        return CoordinatorError(ErrorCode.PROVIDER_ERROR, message, status_code=status, usage_records=records)

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        value = str(text or "").strip()
        if value.startswith("```"):
            lines = value.splitlines()
            value = "\n".join(lines[1:-1] if len(lines) >= 3 else lines).strip()
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("Provider output must be a JSON object")
        return parsed

    def analyze_event(
        self,
        handoff: dict[str, Any],
        *,
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del request_context
        records: list[dict[str, Any]] = []
        structured = self.structured_outputs
        try:
            response, usage = self._call(handoff, structured=structured)
            records.append(usage)
        except _CallFailure as failure:
            records.append(failure.usage_record)
            if structured and self.allow_json_fallback and self._structured_unavailable(failure.cause):
                records[-1]["error_type"] = "STRUCTURED_OUTPUT_UNAVAILABLE"
                try:
                    response, usage = self._call(handoff, structured=False)
                    records.append(usage)
                    structured = False
                except _CallFailure as fallback_failure:
                    records.append(fallback_failure.usage_record)
                    raise self._map_error(fallback_failure.cause, records) from fallback_failure.cause
            else:
                raise self._map_error(failure.cause, records) from failure.cause
        try:
            analysis = self._parse_json(getattr(response, "output_text", ""))
        except (json.JSONDecodeError, ValueError) as error:
            records[-1]["success"] = False
            records[-1]["error_type"] = ErrorCode.INVALID_RESPONSE.value
            raise CoordinatorError(
                ErrorCode.INVALID_RESPONSE,
                safe_error_message(error),
                usage_records=records,
            ) from error
        return {
            "analysis": analysis,
            "usage_records": records,
            "request_id": records[-1].get("request_id"),
            "structured_output": structured,
            "fallback_used": not structured,
        }
