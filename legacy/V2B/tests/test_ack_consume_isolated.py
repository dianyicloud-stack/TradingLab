from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

import pytest

from coordinator.ack_receipt_manager import AckReceiptManager
from coordinator.errors import CoordinatorError


ROOT = Path(__file__).resolve().parents[1]
REAL_STATE = ROOT / "state"
FIXTURE = ROOT / "tests/fixtures/ack_receipt_valid.json"
ISOLATION_PARENT = ROOT / "tests/tmp_ack_consume_state"
ACK_ID = "ACK-20260904-204059-6C2284234584"
DECISION_ID = "DEC-20260903-223831-3CE328"
JOB_ID = "JOB-20260903-223729-EC8F5B"
REVIEW_ID = "REV-20260904-204059-8EC6753AB1F2"


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def state_fingerprint():
    return {
        path.relative_to(REAL_STATE).as_posix(): (
            hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size, path.stat().st_mtime_ns
        )
        for path in sorted(REAL_STATE.rglob("*")) if path.is_file()
    }


def assert_failure(code, operation):
    with pytest.raises(CoordinatorError) as caught:
        operation()
    assert str(caught.value.code) == code


def select_jsonl(source, destination, predicate):
    selected = [item for item in rows(source) if predicate(item)]
    assert selected, f"No required records selected from {source.name}"
    destination.write_text(
        "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in selected),
        encoding="utf-8",
    )


def build_isolated_project(destination):
    destination.mkdir()
    for relative in (
        "config.yaml", "schemas/ack_receipt.schema.json", "schemas/decision.schema.json",
        "schemas/event_handoff.schema.json", "prompts/market_analysis_prompt.txt",
    ):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    state = destination / "state"
    state.mkdir()
    shutil.copy2(REAL_STATE / "pending_ack.json", state / "pending_ack.json")
    shutil.copy2(REAL_STATE / "last_simulated_handoff.json", state / "last_simulated_handoff.json")
    select_jsonl(REAL_STATE / "decisions.jsonl", state / "decisions.jsonl",
                 lambda item: item.get("decision_id") == DECISION_ID)
    select_jsonl(REAL_STATE / "jobs.jsonl", state / "jobs.jsonl",
                 lambda item: item.get("job_id") == JOB_ID)
    select_jsonl(REAL_STATE / "decision_reviews.jsonl", state / "decision_reviews.jsonl",
                 lambda item: item.get("review_id") == REVIEW_ID)
    (destination / "logs").mkdir()
    return state


@pytest.fixture
def isolated_project():
    before = state_fingerprint()
    ISOLATION_PARENT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=ISOLATION_PARENT) as directory:
        project = Path(directory) / "project"
        state = build_isolated_project(project)
        pending = load(state / "pending_ack.json")
        receipt = load(FIXTURE)
        assert pending["ack_id"] == ACK_ID
        assert receipt["ack_payload"] == {key: pending[key] for key in receipt["ack_payload"]}
        assert state_fingerprint() == before
        yield project, state
        assert state_fingerprint() == before
    assert state_fingerprint() == before


def copied_fixture(project, name="ack_receipt_valid.json"):
    target = project / name
    shutil.copy2(FIXTURE, target)
    return target


def test_isolated_success_and_second_consume_are_idempotent(isolated_project):
    project, state = isolated_project
    receipt_path = copied_fixture(project)
    manager = AckReceiptManager(project)

    first = manager.consume(receipt_path)
    assert first["status"] == "CONSUMED"
    assert first["already_consumed"] is False
    assert first["ack_id"] == ACK_ID
    assert first["decision_id"] == DECISION_ID
    assert first["job_id"] == JOB_ID
    assert not (state / "pending_ack.json").exists()

    ledger_after_first = (state / "ack_consumptions.jsonl").read_bytes()
    records = rows(state / "ack_consumptions.jsonl")
    assert len(records) == 1
    assert records[0]["status"] == "CONSUMED"
    assert load(state / "last_ack_receipt.json") == load(FIXTURE)
    status = manager.status()
    assert status["status"] == "CONSUMED"
    assert status["ack_id"] == ACK_ID

    second = AckReceiptManager(project).consume(receipt_path)
    assert second["status"] == "CONSUMED"
    assert second["already_consumed"] is True
    assert second["consumption_id"] == first["consumption_id"]
    assert (state / "ack_consumptions.jsonl").read_bytes() == ledger_after_first
    assert len(rows(state / "ack_consumptions.jsonl")) == 1
    assert not (state / "pending_ack.json").exists()


@pytest.mark.parametrize(("mutation", "error_code"), [
    (lambda receipt: receipt.update(ack_id="ACK-changed"), "RECEIPT_ACK_MISMATCH"),
    (lambda receipt: receipt.update(applied_event_seq=18), "RECEIPT_ACK_MISMATCH"),
    (lambda receipt: receipt.update(applied_observation_time="10:20"), "RECEIPT_ACK_MISMATCH"),
    (lambda receipt: receipt["ack_payload"].update(review_id="REV-changed"),
     "RECEIPT_ACK_PAYLOAD_MISMATCH"),
])
def test_isolated_failure_keeps_pending(isolated_project, mutation, error_code):
    project, state = isolated_project
    receipt = deepcopy(load(FIXTURE))
    mutation(receipt)
    receipt_path = project / "mutated_receipt.json"
    write(receipt_path, receipt)
    pending_before = (state / "pending_ack.json").read_bytes()

    assert_failure(error_code, lambda: AckReceiptManager(project).consume(receipt_path))

    assert (state / "pending_ack.json").read_bytes() == pending_before
    assert not (state / "ack_consumptions.jsonl").exists()
    assert not (state / "last_ack_receipt.json").exists()
