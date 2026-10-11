from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .errors import CoordinatorError
from .request_fingerprint import build_request_fingerprint
from .storage import atomic_write_json, exclusive_file_lock


class RequestArchive:
    """Immutable inputs for later review; uses the existing fingerprint unchanged."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def path_for(self, fingerprint: str) -> Path:
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise CoordinatorError("REQUEST_CONTEXT_INVALID", "Job has no valid request_fingerprint")
        return self.directory / f"{fingerprint}.json"

    @staticmethod
    def validate(fingerprint: str, inputs: dict[str, Any]) -> None:
        try:
            matches = build_request_fingerprint(**inputs) == fingerprint
        except (TypeError, ValueError, KeyError) as error:
            raise CoordinatorError("REQUEST_CONTEXT_INVALID", "Invalid frozen request inputs") from error
        if not matches:
            raise CoordinatorError("REQUEST_CONTEXT_INVALID", "Frozen request does not match Job fingerprint")

    def load(self, fingerprint: str) -> dict[str, Any] | None:
        path = self.path_for(fingerprint)
        if not path.exists():
            return None
        inputs = json.loads(path.read_text(encoding="utf-8"))
        self.validate(fingerprint, inputs)
        return inputs

    def save(self, fingerprint: str, inputs: dict[str, Any]) -> None:
        self.validate(fingerprint, inputs)
        try:
            with exclusive_file_lock(self.directory / "archive.lock"):
                if self.load(fingerprint) is None:
                    atomic_write_json(self.path_for(fingerprint), inputs)
        except (OSError, ValueError) as error:
            raise CoordinatorError("REQUEST_ARCHIVE_FAILED", str(error)) from error
