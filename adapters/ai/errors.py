from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Iterable


class ErrorCode(StrEnum):
    CONFIG_ERROR = "CONFIG_ERROR"
    API_KEY_MISSING = "API_KEY_MISSING"
    AUTH_FAILED = "AUTH_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    EMPTY_PROVIDER_RESPONSE = "EMPTY_PROVIDER_RESPONSE"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    PROVIDER_NOT_IMPLEMENTED = "PROVIDER_NOT_IMPLEMENTED"
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    MODEL_INVALID = "MODEL_INVALID"


def safe_error_message(message: object, secrets: Iterable[str] = ()) -> str:
    text = str(message or "Unknown error")
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", text)
    text = re.sub(r"(?i)authorization\s*[:=]\s*[^\s,;]+", "[REDACTED_HEADER]", text)
    return text[:800]


class CoordinatorError(RuntimeError):
    def __init__(
        self,
        code: ErrorCode | str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        usage_records: list[dict[str, Any]] | None = None,
    ) -> None:
        self.code = ErrorCode(code) if code in ErrorCode._value2member_map_ else str(code)
        self.message = safe_error_message(message)
        self.retryable = retryable
        self.status_code = status_code
        self.usage_records = list(usage_records or [])
        super().__init__(f"{self.code}: {self.message}")
