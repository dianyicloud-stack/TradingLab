from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from .action_policy import build_action_policy_prompt, validate_decision_policy
from .config_manager import ConfigManager
from .decision_manager import DecisionManager
from .decision_store import DecisionStore
from .errors import CoordinatorError
from .event_manager import EventManager
from .job_manager import JobManager
from .models import now_iso, timestamp_id
from .request_archive import RequestArchive
from .storage import JsonlStore, atomic_write_json, exclusive_file_lock


class DecisionReviewManager:
    """Human review only. Never calls an AI provider or writes to V2A."""

    def __init__(self, project_root: Path) -> None:
        self.config = ConfigManager(project_root)
        self.jobs = JobManager(self.config.resolve_path("jobs"))
        self.decisions = DecisionStore(self.config.resolve_path("decisions"))
        self.decision_manager = DecisionManager(self.config.resolve_path("decision_schema"))
        self.event_manager = EventManager(self.config.resolve_path("event_handoff_schema"))
        self.state_dir = self.jobs.store.path.parent
        self.reviews_path = self.state_dir / "decision_reviews.jsonl"
        self.checkpoint_path = self.state_dir / "decision_checkpoint.json"
        self.ack_path = self.state_dir / "pending_ack.json"
        self.transaction_path = self.state_dir / "decision_review_transaction.json"
        self.archive = RequestArchive(self.state_dir / "analysis_requests")

    @contextmanager
    def _locked(self):
        try:
            with exclusive_file_lock(self.state_dir / "decision_reviews.lock"):
                yield
        except (OSError, json.JSONDecodeError) as error:
            raise CoordinatorError("REVIEW_STORAGE_ERROR", str(error)) from error

    @staticmethod
    def _read_json(path):
        if not path.exists():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise CoordinatorError("REVIEW_STORAGE_ERROR", f"Expected JSON object: {path.name}")
        return value

    def _reviews(self):
        if not self.reviews_path.exists():
            return []
        return JsonlStore(self.reviews_path).read_all()

    def _existing_review(self, decision_id):
        return next((r for r in reversed(self._reviews()) if r.get("decision_id") == decision_id), None)

    def _decision_and_job(self, decision_id):
        decision = self.decisions.find(decision_id)
        if decision is None:
            raise CoordinatorError("DECISION_NOT_FOUND", f"Decision not found: {decision_id}")
        with exclusive_file_lock(self.jobs.idempotency_lock_path):
            records = self.jobs.store.read_all()
        related = {r.get("job_id") for r in records if r.get("decision_id") == decision_id}
        if not related:
            raise CoordinatorError("JOB_NOT_FOUND", "No Job is linked to this Decision")
        if len(related) != 1:
            raise CoordinatorError("DECISION_JOB_MISMATCH", "Decision is linked to multiple Jobs")
        job_id = related.pop()
        job = next(r for r in reversed(records) if r.get("job_id") == job_id)
        return decision, job

    @staticmethod
    def _validate_link(decision, job):
        if job.get("decision_id") != decision["decision_id"]:
            raise CoordinatorError("DECISION_JOB_MISMATCH", "Job.decision_id does not match Decision")
        if job.get("status") != "RESULT_READY":
            raise CoordinatorError("JOB_NOT_RESULT_READY", "Job final state must be RESULT_READY")
        for field in ("handoff_id", "tracking_session_id", "provider", "model"):
            if job.get(field) != decision.get(field):
                raise CoordinatorError("DECISION_JOB_MISMATCH", f"Decision/Job {field} mismatch")

    def _legacy_request(self, job):
        """Old jobs are accepted only if the retained simulated Handoff rehashes exactly."""
        handoff = self._read_json(self.state_dir / "last_simulated_handoff.json")
        if handoff is None:
            raise CoordinatorError("REQUEST_CONTEXT_UNAVAILABLE", "Original frozen Handoff is unavailable; cannot safely ACCEPT")
        policy = job.get("action_policy")
        if not isinstance(policy, dict) or "reasoning_effort" not in job:
            raise CoordinatorError("REQUEST_CONTEXT_UNAVAILABLE", "Job lacks the original policy/reasoning snapshot")
        settings = self.config.provider_config(job["provider"])
        prompt = self.config.resolve_path("prompt").read_text(encoding="utf-8")
        inputs = {
            "handoff": handoff,
            "provider": job["provider"],
            "model": job["model"],
            "reasoning_effort": job["reasoning_effort"],
            "action_policy": policy,
            "effective_prompt": f"{prompt.rstrip()}\n\n{build_action_policy_prompt(policy)}\n",
            "decision_schema": self.decision_manager.schema,
            "provider_output_schema": self.decision_manager.provider_output_schema(),
            "provider_request_options": {
                "max_output_tokens": settings.get("max_output_tokens"),
                "structured_outputs": settings.get("structured_outputs", True),
                "allow_json_fallback": settings.get("allow_json_fallback", True),
            },
        }
        self.archive.validate(job["request_fingerprint"], inputs)
        return inputs

    def _validate_accept(self, decision, job):
        self._validate_link(decision, job)
        fingerprint = job.get("request_fingerprint")
        inputs = self.archive.load(fingerprint)
        if inputs is None:
            inputs = self._legacy_request(job)
        for field in ("provider", "model", "reasoning_effort", "action_policy"):
            if inputs.get(field) != job.get(field):
                raise CoordinatorError("REQUEST_CONTEXT_INVALID", f"Frozen request/Job {field} mismatch")
        handoff = inputs["handoff"]
        self.event_manager.validate_handoff(handoff)
        if handoff["trigger_event"]["event_id"] != job.get("event_id"):
            raise CoordinatorError("DECISION_JOB_MISMATCH", "Job trigger event does not match frozen Handoff")
        self.decision_manager.validate_decision(decision, handoff)
        validate_decision_policy(decision, inputs["action_policy"])

    @staticmethod
    def _new_review(decision, job, action, *, note=None, reason=None):
        return {
            "schema_version": "1.0",
            "review_id": timestamp_id("REV", 12),
            "decision_id": decision["decision_id"],
            "job_id": job["job_id"],
            "handoff_id": decision["handoff_id"],
            "tracking_session_id": decision["tracking_session_id"],
            "symbol": decision["symbol"],
            "review_action": action,
            "reviewed_at": now_iso(),
            "reviewed_by": "manual",
            "reason": reason,
            "note": note,
            "request_fingerprint": job.get("request_fingerprint"),
            "action": decision["action"],
            "confidence": decision["confidence"],
            "processed_through_seq": decision["processed_through_seq"],
            "processed_through_observation_time": decision["processed_through_observation_time"],
        }

    @staticmethod
    def _artifacts(decision, job, review):
        checkpoint = {
            "schema_version": "1.0",
            **{key: deepcopy(decision[key]) for key in (
                "decision_id", "handoff_id", "tracking_session_id", "symbol", "analyzed_at",
                "market_state", "structure_state", "action", "key_levels", "invalidation",
                "reason_summary", "confidence", "processed_through_seq",
                "processed_through_observation_time", "provider", "model",
            )},
            "job_id": job["job_id"],
            "accepted_at": review["reviewed_at"],
            "review_id": review["review_id"],
            "request_fingerprint": job["request_fingerprint"],
            "reasoning_effort": job["reasoning_effort"],
            "action_policy": deepcopy(job["action_policy"]),
        }
        ack = {
            "schema_version": "1.0",
            "ack_type": "DECISION_CONFIRMATION",
            "ack_id": review["ack_id"],
            "generated_at": review["reviewed_at"],
            **{key: decision[key] for key in (
                "decision_id", "handoff_id", "tracking_session_id", "symbol",
                "processed_through_seq", "processed_through_observation_time",
            )},
            "job_id": job["job_id"],
            "confirmed_action": decision["action"],
            "request_fingerprint": job["request_fingerprint"],
            "review_id": review["review_id"],
            "source": "V2B_MANUAL_ACCEPT",
        }
        return checkpoint, ack

    def _finish_accept(self, decision, job, review):
        expected = {
            **{key: decision[key] for key in (
                "decision_id", "handoff_id", "tracking_session_id", "symbol", "action",
                "confidence", "processed_through_seq", "processed_through_observation_time",
            )},
            "job_id": job["job_id"], "request_fingerprint": job["request_fingerprint"],
            "review_action": "ACCEPT", "reviewed_by": "manual",
        }
        if any(review.get(key) != value for key, value in expected.items()):
            raise CoordinatorError("REVIEW_STORAGE_ERROR", "Interrupted review does not match its validated Decision/Job")
        checkpoint, ack = self._artifacts(decision, job, review)
        pending = self._read_json(self.ack_path)
        if pending and pending != ack:
            raise CoordinatorError("PENDING_ACK_EXISTS", "A different unconsumed ACK already exists")
        existing = self._existing_review(decision["decision_id"])
        if existing is not None and existing != review:
            raise CoordinatorError("DECISION_ALREADY_FINALIZED", "Decision already has a different finalized review")
        if existing is None:
            JsonlStore(self.reviews_path).append(review)
        # Review is durable before any ACK is published. Retrying an interrupted
        # transaction writes only missing snapshots, using the SAME review/ACK IDs.
        if self._read_json(self.checkpoint_path) != checkpoint:
            atomic_write_json(self.checkpoint_path, checkpoint)
        if pending != ack:
            atomic_write_json(self.ack_path, ack)
        self.transaction_path.unlink()

    def accept(self, decision_id, *, note=None):
        with self._locked():
            transaction = self._read_json(self.transaction_path)
            if transaction:
                if transaction.get("decision_id") != decision_id:
                    raise CoordinatorError("REVIEW_WRITE_INCOMPLETE", "Retry ACCEPT for the interrupted Decision first")
                decision, job = self._decision_and_job(decision_id)
                self._validate_accept(decision, job)
                self._finish_accept(decision, job, transaction)
                return self._review_result(transaction, already=True, recovered=True)
            existing = self._existing_review(decision_id)
            if existing:
                if existing["review_action"] != "ACCEPT":
                    raise CoordinatorError("DECISION_ALREADY_FINALIZED", "REJECTED Decision cannot be ACCEPTED")
                return self._review_result(existing, already=True)
            decision, job = self._decision_and_job(decision_id)
            self._validate_accept(decision, job)
            if self._read_json(self.ack_path):
                raise CoordinatorError("PENDING_ACK_EXISTS", "An unconsumed pending ACK already exists")
            review = self._new_review(decision, job, "ACCEPT", note=note)
            review["ack_id"] = timestamp_id("ACK", 12)
            atomic_write_json(self.transaction_path, review)
            self._finish_accept(decision, job, review)
            return self._review_result(review, already=False)

    def reject(self, decision_id, *, reason=None):
        with self._locked():
            if self.transaction_path.exists():
                raise CoordinatorError("REVIEW_WRITE_INCOMPLETE", "Retry the interrupted ACCEPT first")
            existing = self._existing_review(decision_id)
            if existing:
                if existing["review_action"] != "REJECT":
                    raise CoordinatorError("DECISION_ALREADY_FINALIZED", "ACCEPTED Decision cannot be REJECTED")
                return self._review_result(existing, already=True)
            decision, job = self._decision_and_job(decision_id)
            self._validate_link(decision, job)
            review = self._new_review(decision, job, "REJECT", reason=reason)
            JsonlStore(self.reviews_path).append(review)
            return self._review_result(review, already=False)

    @staticmethod
    def _review_result(review, *, already, recovered=False):
        accepted = review["review_action"] == "ACCEPT"
        return {
            "status": "ACCEPTED" if accepted else "REJECTED",
            "already_accepted" if accepted else "already_rejected": already,
            "api_called": False,
            "review": review,
            "recovered": recovered,
        }

    def show(self, decision_id):
        with self._locked():
            decision, job = self._decision_and_job(decision_id)
            review = self._existing_review(decision_id)
            return {
                "decision": decision, "job": job, "review": review,
                "review_status": ("ACCEPTED" if review["review_action"] == "ACCEPT" else "REJECTED") if review else "UNREVIEWED",
                "write_incomplete": self.transaction_path.exists(),
            }

    def ack_status(self):
        from .ack_receipt_manager import AckReceiptManager

        return AckReceiptManager(self.config.project_root).status()
