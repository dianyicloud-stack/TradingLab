from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

import coordinator.review_manager as review_module
import v2b_coordinator as cli
from coordinator.errors import CoordinatorError
from coordinator.review_manager import DecisionReviewManager
from coordinator.request_fingerprint import build_request_fingerprint
from coordinator.service import V2BCoordinator
from tests.helpers import FakeProvider, fake_factory


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture
def ready(sandbox_project):
    provider = FakeProvider()
    service = V2BCoordinator(sandbox_project, provider_factory=fake_factory(provider))
    handoff = service.build_handoff(sandbox_project / "samples/simulated_event.json")
    result = service.analyze_handoff(handoff, provider_name="deepseek", reasoning_effort="low")
    return service, handoff, result


def assert_failure(code, fn):
    with pytest.raises(CoordinatorError) as caught:
        fn()
    assert str(caught.value.code) == code


def assert_no_ack(manager):
    assert not manager.ack_path.exists()
    assert not manager.checkpoint_path.exists()
    assert rows(manager.reviews_path) == []


def test_t01_missing_decision(sandbox_project):
    manager = DecisionReviewManager(sandbox_project)
    assert_failure("DECISION_NOT_FOUND", lambda: manager.accept("DEC-MISSING"))
    assert_no_ack(manager)


def test_t02_job_not_ready(sandbox_project, ready):
    service, _, result = ready
    service.job_manager.store.append({**result["job"], "status": "FAILED"})
    manager = DecisionReviewManager(sandbox_project)
    assert_failure("JOB_NOT_RESULT_READY", lambda: manager.accept(result["decision"]["decision_id"]))
    assert_no_ack(manager)


@pytest.mark.parametrize("change", [
    {"decision_id": "DEC-WRONG"}, {"tracking_session_id": "TS-WRONG"},
    {"handoff_id": "HO-WRONG"}, {"provider": "openai"}, {"model": "other-model"},
])
def test_t03_job_decision_mismatch(sandbox_project, ready, change):
    service, _, result = ready
    service.job_manager.store.append({**result["job"], **change})
    manager = DecisionReviewManager(sandbox_project)
    assert_failure("DECISION_JOB_MISMATCH", lambda: manager.accept(result["decision"]["decision_id"]))
    assert_no_ack(manager)


def test_missing_job(sandbox_project, ready):
    _, _, result = ready
    (sandbox_project / "state/jobs.jsonl").write_text("", encoding="utf-8")
    manager = DecisionReviewManager(sandbox_project)
    assert_failure("JOB_NOT_FOUND", lambda: manager.accept(result["decision"]["decision_id"]))
    assert_no_ack(manager)


def test_t04_reject_writes_only_review_and_is_idempotent(sandbox_project, ready):
    _, _, result = ready
    manager = DecisionReviewManager(sandbox_project)
    decision_id = result["decision"]["decision_id"]
    original = (sandbox_project / "state/decisions.jsonl").read_bytes()
    rejected = manager.reject(decision_id, reason="不接受")
    assert rejected["status"] == "REJECTED"
    assert not manager.ack_path.exists() and not manager.checkpoint_path.exists()
    before = manager.reviews_path.read_bytes()
    assert manager.reject(decision_id)["already_rejected"] is True
    assert manager.reviews_path.read_bytes() == before
    assert_failure("DECISION_ALREADY_FINALIZED", lambda: manager.accept(decision_id))
    assert (sandbox_project / "state/decisions.jsonl").read_bytes() == original


def test_t05_t06_accept_preserves_decision_and_exact_frozen_cursors(sandbox_project, ready):
    _, _, result = ready
    manager = DecisionReviewManager(sandbox_project)
    originals = {p: p.read_bytes() for p in (
        sandbox_project / "state/jobs.jsonl", sandbox_project / "state/decisions.jsonl",
    )}
    accepted = manager.accept(result["decision"]["decision_id"], note="人工测试")
    assert accepted["status"] == "ACCEPTED" and accepted["already_accepted"] is False
    assert len(rows(manager.reviews_path)) == 1
    checkpoint, ack = read_json(manager.checkpoint_path), read_json(manager.ack_path)
    for document in (checkpoint, ack):
        assert document["processed_through_seq"] == 17
        assert document["processed_through_observation_time"] == "10:15"
        assert document["request_fingerprint"] == result["request_fingerprint"]
        assert document["decision_id"] == result["decision"]["decision_id"]
    assert checkpoint["action_policy"] == result["job"]["action_policy"]
    assert checkpoint["reasoning_effort"] == "low"
    assert ack["source"] == "V2B_MANUAL_ACCEPT" and ack["ack_type"] == "DECISION_CONFIRMATION"
    assert manager.show(result["decision"]["decision_id"])["review_status"] == "ACCEPTED"
    assert manager.ack_status()["status"] == "PENDING"
    assert all(path.read_bytes() == content for path, content in originals.items())


def test_t07_duplicate_accept_does_not_write_or_replace_ack(sandbox_project, ready):
    _, _, result = ready
    manager = DecisionReviewManager(sandbox_project)
    decision_id = result["decision"]["decision_id"]
    first = manager.accept(decision_id)
    snapshots = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (
        manager.reviews_path, manager.checkpoint_path, manager.ack_path,
    )}
    second = DecisionReviewManager(sandbox_project).accept(decision_id, note="ignored duplicate")
    assert second["already_accepted"] is True
    assert second["review"] == first["review"]
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == old for p, old in snapshots.items())


def test_t08_accept_then_reject_fails(sandbox_project, ready):
    _, _, result = ready
    manager = DecisionReviewManager(sandbox_project)
    decision_id = result["decision"]["decision_id"]
    manager.accept(decision_id)
    assert_failure("DECISION_ALREADY_FINALIZED", lambda: manager.reject(decision_id))
    assert len(rows(manager.reviews_path)) == 1


def test_t09_single_pending_blocks_second_accept_but_allows_reject(sandbox_project, ready):
    service, handoff, first = ready
    second = service.analyze_handoff(handoff, provider_name="deepseek", reasoning_effort="low", force=True)
    manager = DecisionReviewManager(sandbox_project)
    manager.accept(first["decision"]["decision_id"])
    before = {p: p.read_bytes() for p in (manager.checkpoint_path, manager.ack_path, manager.reviews_path)}
    assert_failure("PENDING_ACK_EXISTS", lambda: manager.accept(second["decision"]["decision_id"]))
    assert all(p.read_bytes() == value for p, value in before.items())
    manager.reject(second["decision"]["decision_id"])
    assert len(rows(manager.reviews_path)) == 2
    assert manager.ack_path.read_bytes() == before[manager.ack_path]
    assert manager.checkpoint_path.read_bytes() == before[manager.checkpoint_path]


@pytest.mark.parametrize("change", [
    {"action": "INVALID"}, {"processed_through_seq": 18},
    {"processed_through_observation_time": "10:20"},
])
def test_invalid_schema_or_cursor_cannot_be_accepted(sandbox_project, ready, change):
    service, _, result = ready
    service.decision_store.append({**result["decision"], **change})
    manager = DecisionReviewManager(sandbox_project)
    assert_failure("SCHEMA_VALIDATION_FAILED", lambda: manager.accept(result["decision"]["decision_id"]))
    assert_no_ack(manager)


def test_fingerprint_or_archived_handoff_tampering_fails(sandbox_project, ready):
    _, _, result = ready
    manager = DecisionReviewManager(sandbox_project)
    path = manager.archive.path_for(result["request_fingerprint"])
    inputs = read_json(path)
    inputs["handoff"]["current_state"]["price"] = 999
    path.write_text(json.dumps(inputs), encoding="utf-8")
    assert_failure("REQUEST_CONTEXT_INVALID", lambda: manager.accept(result["decision"]["decision_id"]))
    assert_no_ack(manager)


def test_no_context_and_no_fingerprint_fail_closed(sandbox_project, ready):
    service, _, result = ready
    manager = DecisionReviewManager(sandbox_project)
    manager.archive.path_for(result["request_fingerprint"]).unlink()
    assert_failure("REQUEST_CONTEXT_UNAVAILABLE", lambda: manager.accept(result["decision"]["decision_id"]))
    service.job_manager.store.append({**result["job"], "request_fingerprint": None})
    assert_failure("REQUEST_CONTEXT_INVALID", lambda: manager.accept(result["decision"]["decision_id"]))
    assert_no_ack(manager)


@pytest.mark.parametrize("filename", ["decision_checkpoint.json", "pending_ack.json"])
def test_interrupted_accept_recovers_same_review_and_ack(sandbox_project, ready, monkeypatch, filename):
    _, _, result = ready
    manager = DecisionReviewManager(sandbox_project)
    decision_id = result["decision"]["decision_id"]
    real_write = review_module.atomic_write_json

    def fail_write(path, value):
        if path.name == filename:
            raise OSError("simulated write failure")
        real_write(path, value)

    monkeypatch.setattr(review_module, "atomic_write_json", fail_write)
    assert_failure("REVIEW_STORAGE_ERROR", lambda: manager.accept(decision_id))
    review = rows(manager.reviews_path)[0]
    assert manager.transaction_path.exists()
    assert not manager.ack_path.exists()
    monkeypatch.setattr(review_module, "atomic_write_json", real_write)
    recovered = DecisionReviewManager(sandbox_project).accept(decision_id)
    assert recovered["recovered"] is True and recovered["already_accepted"] is True
    assert len(rows(manager.reviews_path)) == 1
    assert read_json(manager.ack_path)["ack_id"] == review["ack_id"]
    assert not manager.transaction_path.exists()


def test_two_simultaneous_accepts_only_publish_one_pending(sandbox_project, ready):
    service, handoff, first = ready
    second = service.analyze_handoff(handoff, provider_name="deepseek", reasoning_effort="low", force=True)

    def accept(result):
        try:
            return DecisionReviewManager(sandbox_project).accept(result["decision"]["decision_id"])["status"]
        except CoordinatorError as error:
            return str(error.code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(accept, (first, second)))
    assert sorted(results) == ["ACCEPTED", "PENDING_ACK_EXISTS"]
    manager = DecisionReviewManager(sandbox_project)
    assert len(rows(manager.reviews_path)) == 1


def test_null_observation_cursor_is_not_inferred(sandbox_project):
    service = V2BCoordinator(sandbox_project, provider_factory=fake_factory(FakeProvider()))
    handoff = service.build_handoff(sandbox_project / "samples/simulated_event.json")
    handoff["observation_rows_since_checkpoint"] = []
    handoff["cursor_snapshot"]["last_processed_observation_time"] = None
    handoff["cursor_snapshot"]["handoff_max_observation_time"] = None
    result = service.analyze_handoff(handoff)
    manager = DecisionReviewManager(sandbox_project)
    manager.accept(result["decision"]["decision_id"])
    ack = read_json(manager.ack_path)
    assert ack["processed_through_seq"] == 17
    assert ack["processed_through_observation_time"] is None


def test_cli_accept_show_reject_ack_without_ai(sandbox_project, ready, monkeypatch, capsys):
    _, _, result = ready
    decision_id = result["decision"]["decision_id"]
    monkeypatch.setattr(cli, "ROOT", sandbox_project)
    def no_ai(*args, **kwargs):
        pytest.fail("Review must never construct an AI Coordinator")
    monkeypatch.setattr(cli, "V2BCoordinator", no_ai)
    assert cli.main(["ack", "status"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "NONE"
    assert cli.main(["decision", "show", "--decision-id", decision_id]) == 0
    assert json.loads(capsys.readouterr().out)["review_status"] == "UNREVIEWED"
    assert cli.main(["decision", "accept", "--decision-id", decision_id, "--note", "cli test"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ACCEPTED"
    assert cli.main(["ack", "status"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PENDING"
    assert cli.main(["decision", "reject", "--decision-id", decision_id, "--reason", "no flip"]) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == "DECISION_ALREADY_FINALIZED"


def test_legacy_simulated_handoff_fallback_requires_exact_hash(sandbox_project, ready):
    _, handoff, result = ready
    manager = DecisionReviewManager(sandbox_project)
    manager.archive.path_for(result["request_fingerprint"]).unlink()
    (sandbox_project / "state/last_simulated_handoff.json").write_text(json.dumps(handoff), encoding="utf-8")
    assert manager.accept(result["decision"]["decision_id"])["status"] == "ACCEPTED"


def test_handoff_semantic_completeness_is_revalidated(sandbox_project, ready):
    service, _, result = ready
    manager = DecisionReviewManager(sandbox_project)
    inputs = manager.archive.load(result["request_fingerprint"])
    inputs["handoff"]["events_since_checkpoint"] = inputs["handoff"]["events_since_checkpoint"][1:]
    fingerprint = build_request_fingerprint(**inputs)
    manager.archive.save(fingerprint, inputs)
    service.job_manager.store.append({**result["job"], "request_fingerprint": fingerprint})
    assert_failure("HANDOFF_SEMANTIC_VALIDATION_FAILED", lambda: manager.accept(result["decision"]["decision_id"]))
    assert_no_ack(manager)


def test_same_decision_concurrent_accept_is_idempotent(sandbox_project, ready):
    _, _, result = ready
    decision_id = result["decision"]["decision_id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: DecisionReviewManager(sandbox_project).accept(decision_id), range(2)))
    assert sorted(r["already_accepted"] for r in results) == [False, True]
    assert results[0]["review"]["ack_id"] == results[1]["review"]["ack_id"]
    assert len(rows(sandbox_project / "state/decision_reviews.jsonl")) == 1


def test_malformed_pending_ack_is_not_overwritten(sandbox_project, ready):
    _, _, result = ready
    manager = DecisionReviewManager(sandbox_project)
    manager.ack_path.write_text("{broken", encoding="utf-8")
    assert_failure("REVIEW_STORAGE_ERROR", lambda: manager.accept(result["decision"]["decision_id"]))
    assert manager.ack_path.read_text(encoding="utf-8") == "{broken"
    assert rows(manager.reviews_path) == []
