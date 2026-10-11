from __future__ import annotations

import logging
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from providers import build_provider

from .action_policy import build_action_policy_prompt, validate_decision_policy
from .config_manager import ConfigManager, DEEPSEEK_REASONING_EFFORTS
from .decision_manager import DecisionManager
from .decision_store import DecisionStore
from .errors import CoordinatorError, ErrorCode, safe_error_message
from .event_manager import EventManager
from .job_manager import JobManager
from .models import json_size_bytes
from .request_fingerprint import build_request_fingerprint
from .request_archive import RequestArchive
from .usage_manager import UsageManager


ProviderFactory = Callable[[str, dict[str, Any], str, dict[str, Any]], Any]


class V2BCoordinator:
    def __init__(
        self,
        project_root: Path,
        *,
        session_provider: str | None = None,
        provider_factory: ProviderFactory | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.config = ConfigManager(self.project_root)
        self.session_provider = session_provider
        self.sleep_fn = sleep_fn
        self.provider_factory = provider_factory or self._default_provider_factory
        self.event_manager = EventManager(self.config.resolve_path("event_handoff_schema"))
        self.decision_manager = DecisionManager(self.config.resolve_path("decision_schema"))
        self.job_manager = JobManager(self.config.resolve_path("jobs"))
        self.decision_store = DecisionStore(self.config.resolve_path("decisions"))
        self.usage_manager = UsageManager(self.config.resolve_path("api_usage"))
        self.prompt = self.config.resolve_path("prompt").read_text(encoding="utf-8")
        self.logger = self._build_logger(self.config.resolve_path("coordinator_log"))

    @staticmethod
    def _default_provider_factory(
        name: str,
        config: dict[str, Any],
        prompt: str,
        output_schema: dict[str, Any],
    ) -> Any:
        return build_provider(name, config, prompt=prompt, output_schema=output_schema)

    @staticmethod
    def _build_logger(path: Path) -> logging.Logger:
        path.parent.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger(f"v2b.coordinator.{path.resolve()}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if not logger.handlers:
            handler = logging.FileHandler(path, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s level=%(levelname)s %(message)s"))
            logger.addHandler(handler)
        return logger

    def _log(self, level: int, *, job: dict[str, Any], handoff: dict[str, Any], stage: str, message: str) -> None:
        self.logger.log(
            level,
            "job_id=%s handoff_id=%s provider=%s stage=%s message=%s",
            job.get("job_id"),
            handoff.get("handoff_id"),
            job.get("provider"),
            stage,
            safe_error_message(message),
        )

    def build_handoff(self, event_path: Path) -> dict[str, Any]:
        event_input = self.event_manager.load_event(event_path)
        return self.event_manager.build_handoff(event_input)

    def _record_usage(
        self,
        records: list[dict[str, Any]],
        *,
        job: dict[str, Any],
        handoff: dict[str, Any],
        provider_name: str,
        model: str,
        attempt: int,
        pricing: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            self.usage_manager.record(
                job=job,
                handoff=handoff,
                provider=provider_name,
                model=model,
                attempt=attempt,
                usage=record,
                pricing=pricing,
            )
            for record in records
        ]

    def analyze_event(
        self,
        event_path: Path,
        *,
        provider_name: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        handoff = self.build_handoff(event_path)
        return self.analyze_handoff(handoff, provider_name=provider_name, force=force)

    def analyze(
        self,
        event_path: Path,
        *,
        cli_provider: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Backward-compatible alias for analyze_event()."""
        return self.analyze_event(event_path, provider_name=cli_provider, force=force)

    def analyze_handoff_file(
        self,
        handoff_path: Path,
        *,
        provider_name: str | None = None,
        reasoning_effort: str | None = None,
        action_policy_mode: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        handoff = self.event_manager.load_event(handoff_path)
        return self.analyze_handoff(
            handoff,
            provider_name=provider_name,
            reasoning_effort=reasoning_effort,
            action_policy_mode=action_policy_mode,
            force=force,
        )

    def analyze_handoff(
        self,
        handoff: dict[str, Any],
        *,
        provider_name: str | None = None,
        reasoning_effort: str | None = None,
        action_policy_mode: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        frozen_handoff = deepcopy(handoff)
        self.event_manager.validate_handoff(frozen_handoff)
        handoff = frozen_handoff
        provider_name = self.config.resolve_provider(provider_name, self.session_provider)
        if reasoning_effort is not None and provider_name != "deepseek":
            raise CoordinatorError(
                ErrorCode.CONFIG_ERROR,
                "reasoning override is currently supported for deepseek only",
            )
        if reasoning_effort is not None and reasoning_effort not in DEEPSEEK_REASONING_EFFORTS:
            allowed = ", ".join(sorted(DEEPSEEK_REASONING_EFFORTS))
            raise CoordinatorError(
                ErrorCode.CONFIG_ERROR,
                f"DeepSeek reasoning override must be one of: {allowed}",
            )
        provider_config = self.config.provider_config(provider_name)
        if reasoning_effort is not None:
            provider_config["reasoning_effort"] = reasoning_effort
        resolved_reasoning_effort = (
            provider_config.get("reasoning_effort", "none") if provider_name == "deepseek" else None
        )
        resolved_action_policy = self.config.action_policy(action_policy_mode)
        model = str(provider_config.get("model") or "UNCONFIGURED")
        effective_prompt = f"{self.prompt.rstrip()}\n\n{build_action_policy_prompt(resolved_action_policy)}\n"
        provider_output_schema = self.decision_manager.provider_output_schema()
        request_inputs = dict(
            handoff=handoff,
            provider=provider_name,
            model=model,
            reasoning_effort=resolved_reasoning_effort,
            action_policy=resolved_action_policy,
            effective_prompt=effective_prompt,
            decision_schema=self.decision_manager.schema,
            provider_output_schema=provider_output_schema,
            provider_request_options={
                "max_output_tokens": provider_config.get("max_output_tokens"),
                "structured_outputs": provider_config.get("structured_outputs", True),
                "allow_json_fallback": provider_config.get("allow_json_fallback", True),
            },
        )
        request_fingerprint = build_request_fingerprint(**request_inputs)
        RequestArchive(self.job_manager.store.path.parent / "analysis_requests").save(
            request_fingerprint, request_inputs,
        )

        def valid_decision_lookup(decision_id: str) -> dict[str, Any] | None:
            decision = self.decision_store.find(decision_id)
            if decision is None:
                return None
            try:
                self.decision_manager.validate_decision(decision, handoff)
                validate_decision_policy(decision, resolved_action_policy)
            except CoordinatorError:
                return None
            if decision.get("provider") != provider_name or decision.get("model") != model:
                return None
            return deepcopy(decision)

        claim = self.job_manager.claim_request(
            handoff,
            provider_name,
            model,
            reasoning_effort=resolved_reasoning_effort,
            action_policy=resolved_action_policy,
            request_fingerprint=request_fingerprint,
            forced=force,
            decision_lookup=valid_decision_lookup,
        )
        job = claim["job"]
        if claim["outcome"] == "REUSED":
            return {
                "job": job,
                "handoff": handoff,
                "decision": claim["decision"],
                "usage": [],
                "reasoning_effort": resolved_reasoning_effort,
                "action_policy": resolved_action_policy["mode"],
                "request_fingerprint": request_fingerprint,
                "reused": True,
                "api_called": False,
                "forced": False,
            }
        if claim["outcome"] == "IN_PROGRESS":
            return {
                "status": "JOB_IN_PROGRESS",
                "job": job,
                "handoff": handoff,
                "decision": None,
                "usage": [],
                "reasoning_effort": resolved_reasoning_effort,
                "action_policy": resolved_action_policy["mode"],
                "request_fingerprint": request_fingerprint,
                "reused": True,
                "api_called": False,
                "forced": bool(job.get("forced")),
            }
        self._log(
            logging.INFO,
            job=job,
            handoff=handoff,
            stage="QUEUED",
            message=f"symbol={handoff['symbol']} size_bytes={json_size_bytes(handoff)} observations={len(handoff['observation_rows_since_checkpoint'])}",
        )
        try:
            provider = self.provider_factory(
                provider_name,
                provider_config,
                effective_prompt,
                provider_output_schema,
            )
            configure_decision_schema = getattr(provider, "configure_decision_schema", None)
            if provider_name == "deepseek" and callable(configure_decision_schema):
                configure_decision_schema(self.decision_manager.analysis_schema())
        except CoordinatorError as error:
            job = self.job_manager.transition(job, "FAILED", error_code=str(error.code))
            self._log(logging.ERROR, job=job, handoff=handoff, stage="PROVIDER_INIT", message=error.message)
            raise

        max_retries = max(0, int(provider_config.get("max_retries") or 0))
        retry_base = max(0.0, float(provider_config.get("retry_base_seconds") or 1.0))
        pricing = provider_config.get("pricing") or {}
        all_usage: list[dict[str, Any]] = []
        for attempt in range(1, max_retries + 2):
            job = self.job_manager.transition(job, "RUNNING", attempt=attempt)
            self._log(logging.INFO, job=job, handoff=handoff, stage="RUNNING", message=f"attempt={attempt}")
            usage_logged = False
            try:
                result = provider.analyze_event(
                    deepcopy(handoff),
                    request_context={"job_id": job["job_id"], "attempt": attempt},
                )
                usage_records = list(result.get("usage_records") or [])
                if usage_records:
                    all_usage.extend(self._record_usage(
                        usage_records,
                        job=job,
                        handoff=handoff,
                        provider_name=provider_name,
                        model=model,
                        attempt=attempt,
                        pricing=pricing,
                    ))
                    usage_logged = True
                try:
                    decision = self.decision_manager.build_decision(
                        result.get("analysis"),
                        handoff=handoff,
                        provider=provider_name,
                        model=model,
                    )
                except CoordinatorError as validation_error:
                    repair_analysis = getattr(provider, "repair_analysis", None)
                    if (
                        provider_name != "deepseek"
                        or validation_error.code != ErrorCode.SCHEMA_VALIDATION_FAILED
                        or not callable(repair_analysis)
                    ):
                        raise
                    try:
                        repair_result = repair_analysis(
                            result.get("analysis"),
                            validator_error=validation_error.message,
                        )
                    except CoordinatorError as repair_error:
                        if repair_error.usage_records:
                            all_usage.extend(self._record_usage(
                                repair_error.usage_records,
                                job=job,
                                handoff=handoff,
                                provider_name=provider_name,
                                model=model,
                                attempt=attempt,
                                pricing=pricing,
                            ))
                        raise
                    repair_usage_records = list(repair_result.get("usage_records") or [])
                    if repair_usage_records:
                        all_usage.extend(self._record_usage(
                            repair_usage_records,
                            job=job,
                            handoff=handoff,
                            provider_name=provider_name,
                            model=model,
                            attempt=attempt,
                            pricing=pricing,
                        ))
                    decision = self.decision_manager.build_decision(
                        repair_result.get("analysis"),
                        handoff=handoff,
                        provider=provider_name,
                        model=model,
                    )
                validate_decision_policy(decision, resolved_action_policy)
                self.decision_store.append(decision)
                job = self.job_manager.transition(job, "RESULT_READY", attempt=attempt, decision_id=decision["decision_id"])
                self._log(logging.INFO, job=job, handoff=handoff, stage="RESULT_READY", message=f"decision_id={decision['decision_id']}")
                return {
                    "job": job,
                    "handoff": handoff,
                    "decision": decision,
                    "usage": all_usage,
                    "reasoning_effort": resolved_reasoning_effort,
                    "action_policy": resolved_action_policy["mode"],
                    "request_fingerprint": request_fingerprint,
                    "reused": False,
                    "api_called": True,
                    "forced": bool(force),
                }
            except CoordinatorError as error:
                if error.usage_records and not usage_logged:
                    all_usage.extend(self._record_usage(
                        error.usage_records,
                        job=job,
                        handoff=handoff,
                        provider_name=provider_name,
                        model=model,
                        attempt=attempt,
                        pricing=pricing,
                    ))
                if error.retryable and attempt <= max_retries:
                    self._log(logging.WARNING, job=job, handoff=handoff, stage="RETRY", message=f"{error.code} attempt={attempt}")
                    self.sleep_fn(retry_base * (2 ** (attempt - 1)))
                    continue
                job = self.job_manager.transition(job, "FAILED", attempt=attempt, error_code=str(error.code))
                self._log(logging.ERROR, job=job, handoff=handoff, stage="FAILED", message=f"{error.code}: {error.message}")
                raise
            except Exception as error:
                wrapped = CoordinatorError(ErrorCode.PROVIDER_ERROR, safe_error_message(error))
                job = self.job_manager.transition(job, "FAILED", attempt=attempt, error_code=str(wrapped.code))
                self._log(logging.ERROR, job=job, handoff=handoff, stage="FAILED", message=wrapped.message)
                raise wrapped from error
        raise AssertionError("Coordinator retry loop ended unexpectedly")
