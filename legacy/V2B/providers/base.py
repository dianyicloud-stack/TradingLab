from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AIProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def analyze_event(
        self,
        handoff: dict[str, Any],
        *,
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform one provider attempt and return analysis plus request metadata."""
        raise NotImplementedError
