from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .errors import CoordinatorError, ErrorCode
from .models import JOB_STATUSES, new_job_id, now_iso
from .storage import JsonlStore, exclusive_file_lock


ALLOWED_TRANSITIONS = {
    "QUEUED": {"RUNNING", "FAILED"},
    "RUNNING": {"RUNNING", "RESULT_READY", "FAILED"},
    "RESULT_READY": set(),
    "FAILED": set(),
}


class JobManager:
    def __init__(self, path: Path) -> None:
        self.store = JsonlStore(path)
        self.idempotency_lock_path = self.store.path.with_name(f"{self.store.path.name}.idempotency.lock")

    def _build_job(
        self,
        handoff: dict[str, Any],
        provider: str,
        model: str,
        *,
        reasoning_effort: str | None,
        action_policy: dict[str, Any] | None,
        request_fingerprint: str | None,
        forced: bool,
    ) -> dict[str, Any]:
        now = now_iso()
        return {
            "schema_version": "1.0",
            "job_id": new_job_id(),
            "event_id": handoff["trigger_event"]["event_id"],
            "handoff_id": handoff["handoff_id"],
            "tracking_session_id": handoff["tracking_session_id"],
            "provider": provider,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "action_policy": deepcopy(action_policy) if action_policy is not None else None,
            "request_fingerprint": request_fingerprint,
            "forced": bool(forced),
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "status": "QUEUED",
            "attempt": 0,
            "error_code": None,
            "decision_id": None,
        }

    def _create_unlocked(
        self,
        handoff: dict[str, Any],
        provider: str,
        model: str,
        *,
        reasoning_effort: str | None,
        action_policy: dict[str, Any] | None,
        request_fingerprint: str | None,
        forced: bool,
    ) -> dict[str, Any]:
        job = self._build_job(
            handoff,
            provider,
            model,
            reasoning_effort=reasoning_effort,
            action_policy=action_policy,
            request_fingerprint=request_fingerprint,
            forced=forced,
        )
        self.store.append(job)
        return job

    def create(
        self,
        handoff: dict[str, Any],
        provider: str,
        model: str,
        *,
        reasoning_effort: str | None = None,
        action_policy: dict[str, Any] | None = None,
        request_fingerprint: str | None = None,
        forced: bool = False,
    ) -> dict[str, Any]:
        with exclusive_file_lock(self.idempotency_lock_path):
            return self._create_unlocked(
                handoff,
                provider,
                model,
                reasoning_effort=reasoning_effort,
                action_policy=action_policy,
                request_fingerprint=request_fingerprint,
                forced=forced,
            )

    def claim_request(
        self,
        handoff: dict[str, Any],
        provider: str,
        model: str,
        *,
        reasoning_effort: str | None,
        action_policy: dict[str, Any],
        request_fingerprint: str,
        forced: bool,
        decision_lookup: Callable[[str], dict[str, Any] | None],
    ) -> dict[str, Any]:
        with exclusive_file_lock(self.idempotency_lock_path):
            latest_jobs: list[dict[str, Any]] = []
            seen_job_ids: set[str] = set()
            for record in reversed(self.store.read_all()):
                if record.get("request_fingerprint") != request_fingerprint:
                    continue
                job_id = record.get("job_id")
                if not isinstance(job_id, str) or job_id in seen_job_ids:
                    continue
                seen_job_ids.add(job_id)
                latest_jobs.append(record)

            active = next(
                (job for job in latest_jobs if job.get("status") in {"QUEUED", "RUNNING"}),
                None,
            )
            if active is not None:
                return {"outcome": "IN_PROGRESS", "job": active, "decision": None}
            if not forced:
                for existing in latest_jobs:
                    if existing.get("status") != "RESULT_READY":
                        continue
                    decision_id = existing.get("decision_id")
                    decision = decision_lookup(decision_id) if isinstance(decision_id, str) and decision_id else None
                    if decision is not None:
                        return {"outcome": "REUSED", "job": existing, "decision": decision}
            job = self._create_unlocked(
                handoff,
                provider,
                model,
                reasoning_effort=reasoning_effort,
                action_policy=action_policy,
                request_fingerprint=request_fingerprint,
                forced=forced,
            )
            return {"outcome": "CREATED", "job": job, "decision": None}

    def transition(
        self,
        current: dict[str, Any],
        status: str,
        *,
        attempt: int | None = None,
        error_code: str | None = None,
        decision_id: str | None = None,
    ) -> dict[str, Any]:
        if status not in JOB_STATUSES:
            raise CoordinatorError(ErrorCode.JOB_INVALID_TRANSITION, f"Unsupported job status: {status}")
        current_status = current.get("status")
        if current_status not in ALLOWED_TRANSITIONS or status not in ALLOWED_TRANSITIONS[current_status]:
            raise CoordinatorError(
                ErrorCode.JOB_INVALID_TRANSITION,
                f"Job transition {current_status} -> {status} is not allowed",
            )
        if status == "RUNNING" and current_status == "RUNNING":
            current_attempt = int(current.get("attempt") or 0)
            if attempt is None or attempt <= current_attempt:
                raise CoordinatorError(
                    ErrorCode.JOB_INVALID_TRANSITION,
                    "RUNNING retry transition requires a strictly increasing attempt",
                )
        job = deepcopy(current)
        now = now_iso()
        job["status"] = status
        if attempt is not None:
            job["attempt"] = attempt
        if status == "RUNNING" and not job.get("started_at"):
            job["started_at"] = now
        if status in ("RESULT_READY", "FAILED"):
            job["finished_at"] = now
        job["error_code"] = error_code
        if decision_id is not None:
            job["decision_id"] = decision_id
        with exclusive_file_lock(self.idempotency_lock_path):
            self.store.append(job)
        return job
