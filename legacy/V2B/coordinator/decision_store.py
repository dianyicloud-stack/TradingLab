from __future__ import annotations

from pathlib import Path
from typing import Any

from .storage import JsonlStore


class DecisionStore:
    def __init__(self, path: Path) -> None:
        self.store = JsonlStore(path)

    def append(self, decision: dict[str, Any]) -> None:
        self.store.append(decision)

    def find(self, decision_id: str) -> dict[str, Any] | None:
        for decision in reversed(self.store.read_all()):
            if decision.get("decision_id") == decision_id:
                return decision
        return None
