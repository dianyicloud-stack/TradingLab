from __future__ import annotations

import shutil
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sandbox_project(tmp_path: Path) -> Path:
    for relative in (
        "config.yaml",
        "schemas/event_handoff.schema.json",
        "schemas/decision.schema.json",
        "schemas/ack_receipt.schema.json",
        "prompts/market_analysis_prompt.txt",
        "samples/simulated_event.json",
        "samples/simulated_event_no_observation.json",
        "samples/simulated_checkpoint.json",
    ):
        source = PROJECT_ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (tmp_path / "state").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "state" / "jobs.jsonl").touch()
    (tmp_path / "state" / "decisions.jsonl").touch()
    (tmp_path / "logs" / "api_usage.jsonl").touch()
    (tmp_path / "logs" / "coordinator.log").touch()
    return tmp_path
