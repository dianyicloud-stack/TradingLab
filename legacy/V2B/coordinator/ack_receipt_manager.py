from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .config_manager import ConfigManager
from .errors import CoordinatorError
from .models import now_iso, timestamp_id
from .request_fingerprint import canonical_json_bytes, sha256_json
from .review_manager import DecisionReviewManager
from .storage import JsonlStore, atomic_write_json, exclusive_file_lock


# V2A deliberately whitelists these fields; generated_at is NOT part of its ACK payload.
ACK_FIELDS = (
    "schema_version", "ack_type", "ack_id", "decision_id", "job_id", "handoff_id",
    "tracking_session_id", "symbol", "confirmed_action", "processed_through_seq",
    "processed_through_observation_time", "request_fingerprint", "review_id", "source",
)
RECEIPT_ACK_FIELDS = {
    "ack_id": "ack_id", "decision_id": "decision_id", "handoff_id": "handoff_id",
    "tracking_session_id": "tracking_session_id", "symbol": "symbol",
    "applied_event_seq": "processed_through_seq",
    "applied_observation_time": "processed_through_observation_time",
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


class AckReceiptManager:
    """Explicit manual receipt import only; never writes V2A or invokes a provider."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        config = ConfigManager(project_root)
        self.state_dir = config.resolve_path("jobs").parent
        self.ack_path = self.state_dir / "pending_ack.json"
        self.consumptions_path = self.state_dir / "ack_consumptions.jsonl"
        self.receipt_path = self.state_dir / "last_ack_receipt.json"
        self.review_transaction_path = self.state_dir / "decision_review_transaction.json"
        schema = json.loads((self.project_root / "schemas/ack_receipt.schema.json").read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    @contextmanager
    def _locked(self):
        # Same lock/order as human ACCEPT/REJECT: a new pending ACK cannot replace ours mid-commit.
        try:
            with exclusive_file_lock(self.state_dir / "decision_reviews.lock"):
                yield
        except (OSError, ValueError) as error:
            raise CoordinatorError("ACK_CONSUMPTION_STORAGE_ERROR", str(error)) from error

    @staticmethod
    def _load_json(text):
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)

    def _read_pending(self):
        if not self.ack_path.exists():
            return None
        try:
            value = self._load_json(self.ack_path.read_text(encoding="utf-8-sig"))
            if not isinstance(value, dict) or any(key not in value for key in ACK_FIELDS):
                raise ValueError("pending_ack lacks required protocol fields")
            return value
        except (ValueError, OSError) as error:
            raise CoordinatorError("ACK_AUDIT_CHAIN_INVALID", f"Invalid pending_ack: {error}") from error

    def _read_receipt(self, path):
        try:
            value = self._load_json(Path(path).read_text(encoding="utf-8-sig"))
        except OSError as error:
            raise CoordinatorError("RECEIPT_READ_ERROR", str(error)) from error
        except ValueError as error:
            raise CoordinatorError("RECEIPT_SCHEMA_INVALID", str(error)) from error
        error = next(self.validator.iter_errors(value), None)
        if error:
            location = ".".join(map(str, error.absolute_path)) or "root"
            # Do not echo arbitrary receipt contents into diagnostics.
            raise CoordinatorError("RECEIPT_SCHEMA_INVALID", f"Invalid Receipt at {location} ({error.validator})")
        if any(value[key] != value[key].strip() for key in (
                "receipt_id", "ack_id", "decision_id", "handoff_id", "tracking_session_id", "symbol")):
            raise CoordinatorError("RECEIPT_SCHEMA_INVALID", "Receipt identifiers must not have surrounding whitespace")
        try:
            # jsonschema's RFC3339 checker is an optional dependency; enforce it locally as well.
            if datetime.fromisoformat(value["generated_at"].replace("Z", "+00:00")).utcoffset() is None:
                raise ValueError("generated_at needs a timezone")
            canonical_json_bytes(value)  # Also rejects non-finite numbers in extension fields.
        except ValueError as error:
            raise CoordinatorError("RECEIPT_SCHEMA_INVALID", "Invalid generated_at or non-finite JSON") from error
        return value

    def _consumptions(self):
        if not self.consumptions_path.exists():
            return []
        records = []
        try:
            for line in self.consumptions_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = self._load_json(line)
                required = ("consumption_id", "consumed_at", "receipt_id", "ack_id", "decision_id",
                            "job_id", "handoff_id", "tracking_session_id", "symbol", "review_id",
                            "request_fingerprint", "receipt_sha256", "applied_event_seq", "applied_observation_time")
                if (not isinstance(record, dict) or any(key not in record for key in required)
                        or record.get("schema_version") != "1.0" or record.get("status") != "CONSUMED"
                        or record.get("receipt_source") != "V2A"):
                    raise ValueError("Invalid consumption record")
                if any(r["receipt_id"] == record["receipt_id"] or r["ack_id"] == record["ack_id"] for r in records):
                    raise ValueError("Duplicate consumption identity")
                records.append(record)
        except (ValueError, OSError) as error:
            raise CoordinatorError("ACK_CONSUMPTION_STORAGE_ERROR", str(error)) from error
        return records

    @staticmethod
    def _existing(receipt, records):
        digest = sha256_json(receipt)
        for field, code in (("receipt_id", "RECEIPT_ID_CONFLICT"), ("ack_id", "ACK_RECEIPT_CONFLICT")):
            existing = next((r for r in records if r[field] == receipt[field]), None)
            if existing is not None:
                if existing["receipt_sha256"] != digest:
                    raise CoordinatorError(code, f"{field} is already bound to different Receipt facts")
                # Verify the retained audit summary, not just the digest.
                expected = {key: receipt[key] for key in RECEIPT_ACK_FIELDS}
                expected.update({key: receipt["ack_payload"].get(key) for key in ("job_id", "review_id", "request_fingerprint")})
                if any(existing.get(key) != value for key, value in expected.items()):
                    raise CoordinatorError("ACK_CONSUMPTION_STORAGE_ERROR", "Consumption summary does not match Receipt")
                return existing
        return None

    @staticmethod
    def _match_pending(receipt, pending):
        if any(receipt[key] != pending[field] for key, field in RECEIPT_ACK_FIELDS.items()):
            raise CoordinatorError("RECEIPT_ACK_MISMATCH", "Receipt identity or applied cursors differ from pending ACK")
        payload = receipt["ack_payload"]
        if any(key not in payload for key in ACK_FIELDS) or canonical_json_bytes(
                {key: payload[key] for key in ACK_FIELDS}) != canonical_json_bytes(
                {key: pending[key] for key in ACK_FIELDS}):
            raise CoordinatorError("RECEIPT_ACK_PAYLOAD_MISMATCH", "Receipt ACK protocol fields differ from pending ACK")

    def _validate_audit_chain(self, pending):
        try:
            if self.review_transaction_path.exists():
                raise ValueError("An ACCEPT transaction is incomplete; retry that ACCEPT before consuming")
            manager = DecisionReviewManager(self.project_root)
            reviews = manager._reviews()
            linked = [r for r in reviews if r.get("review_id") == pending["review_id"]]
            if len(linked) != 1:
                raise ValueError("Missing or ambiguous Review")
            review = linked[0]
            decision, job = manager._decision_and_job(pending["decision_id"])
            manager._validate_accept(decision, job)  # Existing frozen Handoff/Schema/cursor/policy checks, read-only.
            expected = {key: decision[key] for key in (
                "decision_id", "handoff_id", "tracking_session_id", "symbol", "action", "confidence",
                "processed_through_seq", "processed_through_observation_time",
            )}
            expected.update({"job_id": job["job_id"], "request_fingerprint": job["request_fingerprint"],
                             "review_action": "ACCEPT", "reviewed_by": "manual", "ack_id": pending["ack_id"]})
            if any(review.get(key) != value for key, value in expected.items()):
                raise ValueError("ACCEPT Review does not match Decision/Job/ACK")
            if any(r != review for r in reviews if r.get("decision_id") == pending["decision_id"]):
                raise ValueError("Decision has conflicting reviews")
            _, expected_ack = manager._artifacts(decision, job, review)
            if canonical_json_bytes({key: pending[key] for key in ACK_FIELDS}) != canonical_json_bytes(
                    {key: expected_ack[key] for key in ACK_FIELDS}):
                raise ValueError("Pending ACK does not match accepted Decision/Job/Review")
        except (CoordinatorError, KeyError, TypeError, ValueError, OSError, AttributeError) as error:
            raise CoordinatorError("ACK_AUDIT_CHAIN_INVALID", str(error)) from error

    @staticmethod
    def _new_consumption(receipt, pending):
        return {
            "schema_version": "1.0", "consumption_id": timestamp_id("CON", 12), "consumed_at": now_iso(),
            "receipt_id": receipt["receipt_id"],
            **{key: pending[key] for key in ("ack_id", "decision_id", "job_id", "handoff_id", "tracking_session_id",
                                           "symbol", "review_id", "request_fingerprint")},
            "applied_event_seq": receipt["applied_event_seq"],
            "applied_observation_time": receipt["applied_observation_time"],
            "receipt_source": "V2A", "status": "CONSUMED", "receipt_sha256": sha256_json(receipt),
        }

    @staticmethod
    def _result(record, already):
        return {**record, "already_consumed": already, "api_called": False}

    def consume(self, receipt_path: Path):
        receipt = self._read_receipt(receipt_path)
        with self._locked():
            pending = self._read_pending()
            existing = self._existing(receipt, self._consumptions())
            # An old duplicate must never clear a newer, unrelated pending ACK or replace its snapshots.
            if existing and (pending is None or pending["ack_id"] != receipt["ack_id"]):
                return self._result(existing, True)
            if pending is None:
                raise CoordinatorError("NO_PENDING_ACK", "No pending ACK and no matching consumption fact")
            self._match_pending(receipt, pending)
            self._validate_audit_chain(pending)
            record = existing or self._new_consumption(receipt, pending)
            try:
                if existing is None:
                    JsonlStore(self.consumptions_path).append(record)
                # Durable consumption is the retry anchor. Never append again after a later I/O failure.
                try:
                    snapshot = self._load_json(self.receipt_path.read_text(encoding="utf-8")) if self.receipt_path.exists() else None
                except ValueError:
                    snapshot = None  # Mutable snapshot can be rebuilt from the verified receipt/ledger.
                if canonical_json_bytes(snapshot) != canonical_json_bytes(receipt):
                    atomic_write_json(self.receipt_path, receipt)
                if canonical_json_bytes(self._read_pending()) != canonical_json_bytes(pending):
                    raise ValueError("pending ACK changed during consumption; it was not deleted")
                self.ack_path.unlink()
            except (OSError, ValueError, CoordinatorError) as error:
                raise CoordinatorError("ACK_CONSUMPTION_INCOMPLETE", f"Retry the same Receipt to finish: {error}") from error
            return self._result(record, existing is not None)

    def status(self):
        with self._locked():
            pending = self._read_pending()
            incomplete = self.review_transaction_path.exists()
            if pending is not None:
                return {**pending, "status": "PENDING", "write_incomplete": incomplete}
            if incomplete:
                raise CoordinatorError("REVIEW_WRITE_INCOMPLETE", "ACCEPT committed incompletely; retry the same ACCEPT")
            records = self._consumptions()
            return {**records[-1]} if records else {"status": "NONE"}
