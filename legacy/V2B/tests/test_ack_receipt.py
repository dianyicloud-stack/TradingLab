from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import coordinator.ack_receipt_manager as module
import v2b_coordinator as cli
from coordinator.ack_receipt_manager import ACK_FIELDS, AckReceiptManager
from coordinator.errors import CoordinatorError
from coordinator.review_manager import DecisionReviewManager
from coordinator.service import V2BCoordinator
from tests.helpers import FakeProvider, fake_factory


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def snapshot(paths):
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths if p.exists()}


def fail(code, operation):
    with pytest.raises(CoordinatorError) as caught:
        operation()
    assert str(caught.value.code) == code


def receipt_for(ack):
    # Mirrors the frozen V2A receipt: whitelist ACK fields, NOT the V2B generated_at extension.
    return {
        "schema_version": "1.0", "receipt_type": "ACK_APPLIED", "receipt_id": f"AR-{ack['ack_id']}",
        "generated_at": "2026-09-04T10:20:00+08:00",
        **{key: ack[key] for key in ("ack_id", "decision_id", "handoff_id", "tracking_session_id", "symbol")},
        "applied_event_seq": ack["processed_through_seq"],
        "applied_observation_time": ack["processed_through_observation_time"],
        "status": "APPLIED", "source": "V2A", "previous_event_seq": 15,
        "previous_observation_time": "10:05", "directory_id": "RD-test",
        "ack_payload": {key: ack[key] for key in ACK_FIELDS},
    }


@pytest.fixture
def accepted(sandbox_project):
    service = V2BCoordinator(sandbox_project, provider_factory=fake_factory(FakeProvider()))
    handoff = service.build_handoff(sandbox_project / "samples/simulated_event.json")
    result = service.analyze_handoff(handoff, provider_name="deepseek", reasoning_effort="low")
    review = DecisionReviewManager(sandbox_project)
    review.accept(result["decision"]["decision_id"])
    manager = AckReceiptManager(sandbox_project)
    ack = read(manager.ack_path)
    receipt = receipt_for(ack)
    path = sandbox_project / "external V2A directory/ack_receipt.json"
    write(path, receipt)
    return manager, review, path, receipt, service, handoff


def untouched_history(manager):
    return snapshot([manager.state_dir / name for name in (
        "jobs.jsonl", "decisions.jsonl", "decision_reviews.jsonl", "decision_checkpoint.json",
    )])


def test_t01_t02_t03_consumes_exact_receipt_and_preserves_all_history(accepted):
    manager, review, path, receipt, _, _ = accepted
    original = untouched_history(manager)
    source = snapshot([path])
    assert manager.status()["status"] == "PENDING"
    result = manager.consume(path)
    assert result["status"] == "CONSUMED" and result["already_consumed"] is False
    assert result["api_called"] is False
    assert not manager.ack_path.exists()
    records = rows(manager.consumptions_path)
    assert len(records) == 1 and records[0]["applied_event_seq"] == 17
    assert records[0]["applied_observation_time"] == "10:15"
    assert records[0]["receipt_id"] == receipt["receipt_id"]
    assert records[0]["consumption_id"].startswith("CON-")
    assert read(manager.receipt_path) == receipt
    assert manager.status()["status"] == review.ack_status()["status"] == "CONSUMED"
    assert untouched_history(manager) == original and snapshot([path]) == source


def test_t04_duplicate_across_restart_is_zero_write(accepted):
    manager, _, path, _, _, _ = accepted
    first = manager.consume(path)
    files = snapshot(manager.state_dir.glob("*.json*"))
    second = AckReceiptManager(manager.project_root).consume(path)
    assert second["already_consumed"] is True and second["consumption_id"] == first["consumption_id"]
    assert snapshot(manager.state_dir.glob("*.json*")) == files


@pytest.mark.parametrize("field,value", [
    ("ack_id", "ACK-wrong"), ("decision_id", "DEC-wrong"), ("handoff_id", "HO-wrong"),
    ("tracking_session_id", "TS-20260901-bj920161-99"), ("symbol", "sz301111"),
    ("applied_event_seq", 18), ("applied_observation_time", "10:20"),
])
def test_t05_to_t09_receipt_identity_and_cursor_mismatch_keep_pending(accepted, field, value):
    manager, _, path, receipt, _, _ = accepted
    original = snapshot(manager.state_dir.glob("*.json*"))
    receipt[field] = value
    write(path, receipt)
    fail("RECEIPT_ACK_MISMATCH", lambda: manager.consume(path))
    assert snapshot(manager.state_dir.glob("*.json*")) == original
    assert not manager.consumptions_path.exists()


@pytest.mark.parametrize("field", ACK_FIELDS)
def test_t10_each_ack_payload_protocol_field_must_match(accepted, field):
    manager, _, path, receipt, _, _ = accepted
    receipt["ack_payload"][field] = "tampered"
    write(path, receipt)
    fail("RECEIPT_ACK_PAYLOAD_MISMATCH", lambda: manager.consume(path))
    assert manager.ack_path.exists() and not manager.consumptions_path.exists()


def test_payload_order_is_irrelevant_generated_at_is_optional(accepted):
    manager, _, path, receipt, _, _ = accepted
    receipt["ack_payload"] = dict(reversed(list(receipt["ack_payload"].items())))
    write(path, dict(reversed(list(receipt.items()))))
    assert manager.consume(path)["status"] == "CONSUMED"
    # Reordering the *same* entire receipt remains idempotent (full canonical hash).
    write(path, receipt)
    assert manager.consume(path)["already_consumed"] is True


@pytest.mark.parametrize("damage", [
    "missing_decision", "missing_review", "reject", "review_ack", "review_job", "review_session",
    "review_cursor", "review_fingerprint", "job_handoff", "job_decision", "job_failed", "job_fingerprint",
    "archive_tampered", "pending_and_receipt_action", "unfinished_accept", "non_object_review",
])
def test_t11_t12_internal_chain_damage_cannot_be_consumed(accepted, damage):
    manager, review, path, receipt, _, _ = accepted
    if damage == "missing_decision":
        (manager.state_dir / "decisions.jsonl").write_text("", encoding="utf-8")
    elif damage == "missing_review":
        review.reviews_path.write_text("", encoding="utf-8")
    elif damage == "non_object_review":
        review.reviews_path.write_text("[]\n", encoding="utf-8")
    elif damage.startswith("review_") or damage == "reject":
        record = rows(review.reviews_path)[0]
        changes = {"reject": ("review_action", "REJECT"), "review_ack": ("ack_id", "wrong"),
                   "review_job": ("job_id", "wrong"), "review_session": ("tracking_session_id", "wrong"),
                   "review_cursor": ("processed_through_seq", 18), "review_fingerprint": ("request_fingerprint", "f"*64)}
        key, value = changes[damage]; record[key] = value
        review.reviews_path.write_text(json.dumps(record)+"\n", encoding="utf-8")
    elif damage.startswith("job_"):
        jobs = rows(manager.state_dir / "jobs.jsonl")
        key, value = {"job_handoff": ("handoff_id", "wrong"), "job_decision": ("decision_id", "wrong"),
                      "job_failed": ("status", "FAILED"), "job_fingerprint": ("request_fingerprint", "f"*64)}[damage]
        jobs[-1][key] = value
        (manager.state_dir / "jobs.jsonl").write_text("\n".join(map(json.dumps, jobs))+"\n", encoding="utf-8")
    elif damage == "archive_tampered":
        archive = review.archive.path_for(receipt["ack_payload"]["request_fingerprint"])
        request = read(archive); request["handoff"]["symbol"] = "sz301111"; write(archive, request)
    elif damage == "pending_and_receipt_action":
        pending = read(manager.ack_path); pending["confirmed_action"] = "EXIT"
        receipt["ack_payload"]["confirmed_action"] = "EXIT"
        write(manager.ack_path, pending); write(path, receipt)
    else:
        write(review.transaction_path, rows(review.reviews_path)[0])
    original = snapshot(manager.state_dir.glob("*.json*"))
    fail("ACK_AUDIT_CHAIN_INVALID", lambda: manager.consume(path))
    assert snapshot(manager.state_dir.glob("*.json*")) == original
    assert manager.ack_path.exists() and not manager.consumptions_path.exists()


def test_t13_never_consumed_without_pending_cannot_create_fact(accepted):
    manager, _, path, _, _, _ = accepted
    manager.ack_path.unlink()
    fail("NO_PENDING_ACK", lambda: manager.consume(path))
    assert not manager.consumptions_path.exists() and not manager.receipt_path.exists()
    assert manager.status() == {"status": "NONE"}


@pytest.mark.parametrize("field,value", [
    ("schema_version", "2.0"), ("receipt_type", "OTHER"), ("status", "PENDING"), ("source", "V2B"),
    ("receipt_id", " "), ("generated_at", "not-a-date"), ("ack_id", None), ("decision_id", 5),
    ("generated_at", "2026-02-30T10:20:00+08:00"), ("generated_at", "2026-09-04T10:20:00"),
    ("ack_id", "ACK-trailing\n"), ("applied_observation_time", "10:15\n"),
    ("tracking_session_id", "wrong"), ("symbol", "wrong"), ("applied_event_seq", -1),
    ("applied_event_seq", True), ("applied_event_seq", 1.5), ("applied_event_seq", 9007199254740992),
    ("applied_observation_time", "24:00"), ("applied_observation_time", "9:30"),
    ("ack_payload", []), ("ack_payload", None),
])
def test_t14_invalid_schema(accepted, field, value):
    manager, _, path, receipt, _, _ = accepted
    receipt[field] = value; write(path, receipt)
    fail("RECEIPT_SCHEMA_INVALID", lambda: manager.consume(path))
    assert manager.ack_path.exists() and not manager.consumptions_path.exists()


@pytest.mark.parametrize("text", ["{broken", "[]", "null", '{"ack_id":"a","ack_id":"b"}', '{"extension":NaN}'])
def test_invalid_json_and_duplicate_keys(accepted, text):
    manager, _, path, _, _, _ = accepted
    path.write_text(text, encoding="utf-8")
    fail("RECEIPT_SCHEMA_INVALID", lambda: manager.consume(path))
    assert manager.ack_path.exists()


@pytest.mark.parametrize("change,code", [
    ({"generated_at": "2026-09-04T10:21:00+08:00"}, "RECEIPT_ID_CONFLICT"),
    ({"receipt_id": "AR-another"}, "ACK_RECEIPT_CONFLICT"),
    ({"directory_id": "RD-other"}, "RECEIPT_ID_CONFLICT"),
])
def test_same_receipt_or_ack_id_with_different_facts_conflicts(accepted, change, code):
    manager, _, path, receipt, _, _ = accepted
    manager.consume(path)
    original = snapshot(manager.state_dir.glob("*.json*"))
    receipt.update(change); write(path, receipt)
    fail(code, lambda: manager.consume(path))
    assert snapshot(manager.state_dir.glob("*.json*")) == original


@pytest.mark.parametrize("phase", ["append_before", "append_after", "snapshot", "unlink"])
def test_interrupted_write_retains_pending_and_retry_never_duplicates(accepted, monkeypatch, phase):
    manager, _, path, receipt, _, _ = accepted
    real_append, real_write, real_unlink = module.JsonlStore.append, module.atomic_write_json, Path.unlink
    def append(store, record):
        if store.path == manager.consumptions_path:
            if phase == "append_after":
                real_append(store, record)
            raise OSError("injected append failure")
        real_append(store, record)
    def atomic(path, record):
        if path == manager.receipt_path:
            raise OSError("injected snapshot failure")
        real_write(path, record)
    def unlink(path, *args, **kwargs):
        if path == manager.ack_path:
            raise OSError("injected deletion failure")
        return real_unlink(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        if phase.startswith("append"):
            patch.setattr(module.JsonlStore, "append", append)
        elif phase == "snapshot":
            patch.setattr(module, "atomic_write_json", atomic)
        else:
            patch.setattr(Path, "unlink", unlink)
        fail("ACK_CONSUMPTION_INCOMPLETE", lambda: manager.consume(path))
    assert manager.ack_path.exists() and manager.status()["status"] == "PENDING"
    count = 0 if phase == "append_before" else 1
    assert len(rows(manager.consumptions_path)) == count
    result = AckReceiptManager(manager.project_root).consume(path)
    assert result["already_consumed"] is (count == 1)
    assert len(rows(manager.consumptions_path)) == 1
    assert not manager.ack_path.exists() and read(manager.receipt_path) == receipt


def test_historical_duplicate_never_clears_new_pending_or_reverts_latest_snapshot(accepted):
    manager, review, path, _, service, handoff = accepted
    manager.consume(path)
    second = service.analyze_handoff(handoff, provider_name="deepseek", reasoning_effort="low", force=True)
    review.accept(second["decision"]["decision_id"])
    before = snapshot(manager.state_dir.glob("*.json*"))
    assert manager.consume(path)["already_consumed"] is True
    assert snapshot(manager.state_dir.glob("*.json*")) == before
    assert manager.status()["status"] == "PENDING"
    next_path = path.with_name("next_receipt.json"); write(next_path, receipt_for(read(manager.ack_path)))
    manager.consume(next_path)
    before = snapshot(manager.state_dir.glob("*.json*"))
    manager.consume(path)
    assert snapshot(manager.state_dir.glob("*.json*")) == before
    assert manager.status()["decision_id"] == second["decision"]["decision_id"]


def test_replace_pending_outside_lock_is_not_deleted(accepted, monkeypatch):
    manager, _, path, _, _, _ = accepted
    real_write = module.atomic_write_json
    def write_and_replace(target, value):
        real_write(target, value)
        pending = read(manager.ack_path); pending["ack_id"] = "ACK-newer"; write(manager.ack_path, pending)
    monkeypatch.setattr(module, "atomic_write_json", write_and_replace)
    fail("ACK_CONSUMPTION_INCOMPLETE", lambda: manager.consume(path))
    assert read(manager.ack_path)["ack_id"] == "ACK-newer"
    assert len(rows(manager.consumptions_path)) == 1


def test_incomplete_accept_must_finish_before_consumption(accepted):
    manager, review, path, _, _, _ = accepted
    write(review.transaction_path, rows(review.reviews_path)[0])
    fail("ACK_AUDIT_CHAIN_INVALID", lambda: manager.consume(path))
    review.accept(read(manager.ack_path)["decision_id"])
    manager.consume(path)
    review.accept(rows(review.reviews_path)[0]["decision_id"])
    assert not manager.ack_path.exists()  # Repeated ACCEPT must not resurrect a consumed work item.


def test_null_observation_cursor_is_exact_not_inferred(sandbox_project):
    service = V2BCoordinator(sandbox_project, provider_factory=fake_factory(FakeProvider()))
    handoff = service.build_handoff(sandbox_project / "samples/simulated_event.json")
    handoff["observation_rows_since_checkpoint"] = []
    handoff["cursor_snapshot"]["last_processed_observation_time"] = None
    handoff["cursor_snapshot"]["handoff_max_observation_time"] = None
    result = service.analyze_handoff(handoff)
    DecisionReviewManager(sandbox_project).accept(result["decision"]["decision_id"])
    manager = AckReceiptManager(sandbox_project)
    receipt = receipt_for(read(manager.ack_path)); path = sandbox_project / "receipt.json"; write(path, receipt)
    assert manager.consume(path)["applied_observation_time"] is None


def test_cli_import_and_status_never_construct_ai(accepted, monkeypatch, capsys):
    manager, _, path, _, _, _ = accepted
    monkeypatch.setattr(cli, "ROOT", manager.project_root)
    def no_ai(*args, **kwargs):
        pytest.fail("Receipt consumer must not create an AI Coordinator")
    monkeypatch.setattr(cli, "V2BCoordinator", no_ai)
    assert cli.main(["ack", "status"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PENDING"
    assert cli.main(["ack", "consume", "--receipt", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["already_consumed"] is False
    assert cli.main(["ack", "consume", "--receipt", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["already_consumed"] is True
    assert cli.main(["ack", "status"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "CONSUMED"


def test_concurrent_real_cli_processes_consume_only_once(accepted):
    manager, _, path, _, _, _ = accepted
    source_root = Path(cli.__file__).parent
    isolated_cli = manager.project_root / "v2b_coordinator.py"
    shutil.copy2(cli.__file__, isolated_cli)
    env = {**os.environ, "PYTHONPATH": str(source_root), "PYTHONIOENCODING": "utf-8"}
    def consume(_):
        result = subprocess.run([sys.executable, str(isolated_cli), "ack", "consume", "--receipt", str(path)],
                                capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(consume, range(2)))
    assert sorted(r["already_consumed"] for r in results) == [False, True]
    assert results[0]["consumption_id"] == results[1]["consumption_id"]
    assert len(rows(manager.consumptions_path)) == 1


def test_concurrent_accept_and_consume_share_lock(accepted):
    manager, review, path, _, service, handoff = accepted
    second = service.analyze_handoff(handoff, provider_name="deepseek", reasoning_effort="low", force=True)
    def accept():
        try:
            return review.accept(second["decision"]["decision_id"])["status"]
        except CoordinatorError as error:
            return str(error.code)
    with ThreadPoolExecutor(max_workers=2) as pool:
        consuming = pool.submit(manager.consume, path); accepting = pool.submit(accept)
        assert consuming.result()["status"] == "CONSUMED"
        status = accepting.result()
    if status == "PENDING_ACK_EXISTS":
        review.accept(second["decision"]["decision_id"])
    else:
        assert status == "ACCEPTED"
    assert read(manager.ack_path)["decision_id"] == second["decision"]["decision_id"]


def test_partial_consumption_ledger_fails_closed_without_deleting_pending(accepted):
    manager, _, path, _, _, _ = accepted
    manager.consumptions_path.write_text('{"partial":', encoding="utf-8")
    fail("ACK_CONSUMPTION_STORAGE_ERROR", lambda: manager.consume(path))
    assert manager.ack_path.exists()
    assert manager.consumptions_path.read_text(encoding="utf-8") == '{"partial":'


def test_corrupt_mutable_receipt_snapshot_can_be_rebuilt(accepted):
    manager, _, path, receipt, _, _ = accepted
    manager.receipt_path.write_text('{"partial":', encoding="utf-8")
    assert manager.consume(path)["status"] == "CONSUMED"
    assert read(manager.receipt_path) == receipt


def test_missing_payload_protocol_key_is_not_silently_defaulted(accepted):
    manager, _, path, receipt, _, _ = accepted
    del receipt["ack_payload"]["processed_through_observation_time"]
    write(path, receipt)
    fail("RECEIPT_ACK_PAYLOAD_MISMATCH", lambda: manager.consume(path))
    assert manager.ack_path.exists()


def test_missing_receipt_field_and_missing_file_are_diagnostic(accepted):
    manager, _, path, receipt, _, _ = accepted
    del receipt["applied_observation_time"]; write(path, receipt)
    fail("RECEIPT_SCHEMA_INVALID", lambda: manager.consume(path))
    fail("RECEIPT_READ_ERROR", lambda: manager.consume(path.with_name("missing.json")))
    assert manager.ack_path.exists()


def test_ack_payload_conflict_detected_after_success_without_pending(accepted):
    manager, _, path, receipt, _, _ = accepted
    manager.consume(path)
    receipt["ack_payload"]["confirmed_action"] = "EXIT"; write(path, receipt)
    fail("RECEIPT_ID_CONFLICT", lambda: manager.consume(path))
    assert len(rows(manager.consumptions_path)) == 1
