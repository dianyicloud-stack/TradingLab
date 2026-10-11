from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from coordinator import CoordinatorError, V2BCoordinator
from coordinator.action_policy import ACTION_POLICY_MODES
from coordinator.ack_receipt_manager import AckReceiptManager
from coordinator.config_manager import ConfigManager, DEEPSEEK_REASONING_EFFORTS
from coordinator.review_manager import DecisionReviewManager


ROOT = Path(__file__).resolve().parent
DEFAULT_EVENT = ROOT / "samples" / "simulated_event.json"


def print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def command_doctor() -> int:
    report = ConfigManager(ROOT).doctor()
    print_json(report)
    return 0 if report["ready"] else 1


def command_providers() -> int:
    report = ConfigManager(ROOT).providers_report()
    print(
        f"{'Provider':<14}{'Enabled':<11}{'Implemented':<14}{'Default':<10}"
        f"{'Model':<28}{'Reasoning':<12}MaxOutput"
    )
    for item in report:
        yes_no = lambda value: "YES" if value else "NO"
        reasoning = item.get("reasoning_effort") or "-"
        configured_max = item.get("max_output_tokens")
        max_output = (
            "provider_default"
            if item["provider"] == "deepseek" and configured_max is None
            else str(configured_max) if configured_max is not None else "-"
        )
        print(
            f"{item['provider']:<14}{yes_no(item['enabled']):<11}"
            f"{yes_no(item['implemented']):<14}{yes_no(item['default']):<10}"
            f"{item['model']:<28}{reasoning:<12}{max_output}"
        )
    return 0


def command_simulate(event_path: Path) -> int:
    coordinator = V2BCoordinator(ROOT)
    handoff = coordinator.build_handoff(event_path)
    output_path = ROOT / "state" / "last_simulated_handoff.json"
    output_path.write_text(json.dumps(handoff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_json({
        "status": "SIMULATED",
        "api_called": False,
        "handoff_path": str(output_path),
        "handoff": handoff,
    })
    return 0


def print_analysis_result(result: dict) -> int:
    usage = result["usage"][-1] if result["usage"] else {}
    decision = result.get("decision")
    if decision is None:
        output = {
            "status": result.get("status", "JOB_IN_PROGRESS"),
            "reused": bool(result.get("reused")),
            "api_called": bool(result.get("api_called")),
            "job_id": result["job"]["job_id"],
            "provider": result["job"]["provider"],
            "model": result["job"]["model"],
            "reasoning_effort": result.get("reasoning_effort"),
            "action_policy": result.get("action_policy"),
            "request_fingerprint": result.get("request_fingerprint"),
        }
        print_json(output)
        return 0
    output = {
        "status": result["job"]["status"],
        "job_id": result["job"]["job_id"],
        "provider": decision["provider"],
        "model": decision["model"],
        "latency_ms": usage.get("latency_ms"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "reasoning_tokens": usage.get("reasoning_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "decision_id": decision["decision_id"],
        "action": decision["action"],
        "schema": "PASS",
    }
    if result.get("reasoning_effort") is not None:
        output["reasoning_effort"] = result["reasoning_effort"]
    if result.get("action_policy") is not None:
        output["action_policy"] = result["action_policy"]
    for field in ("request_fingerprint", "reused", "api_called", "forced"):
        if field in result:
            output[field] = result[field]
    print_json(output)
    return 0


def command_analyze(event_path: Path, provider: str | None, session_provider: str | None) -> int:
    coordinator = V2BCoordinator(ROOT, session_provider=session_provider)
    return print_analysis_result(coordinator.analyze_event(event_path, provider_name=provider))


def command_analyze_handoff(
    handoff_path: Path,
    provider: str | None,
    session_provider: str | None,
    reasoning: str | None,
    action_policy: str | None,
    force: bool = False,
) -> int:
    coordinator = V2BCoordinator(ROOT, session_provider=session_provider)
    return print_analysis_result(coordinator.analyze_handoff_file(
        handoff_path,
        provider_name=provider,
        reasoning_effort=reasoning,
        action_policy_mode=action_policy,
        force=force,
    ))


def reasoning_effort_for_error(args: argparse.Namespace) -> str | None:
    requested = getattr(args, "reasoning", None)
    if requested is not None:
        return requested
    if getattr(args, "command", None) != "analyze-handoff":
        return None
    try:
        config = ConfigManager(ROOT)
        provider = config.resolve_provider(
            getattr(args, "provider", None),
            getattr(args, "session_provider", None),
        )
        if provider == "deepseek":
            return config.provider_config("deepseek").get("reasoning_effort", "none")
    except CoordinatorError:
        return None
    return None


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="V2B isolated Event → AI → Decision coordinator")
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="check config, dependencies and API key presence")
    commands.add_parser("providers", help="list configured providers")
    simulate = commands.add_parser("simulate", help="build an Event Handoff without calling an API")
    simulate.add_argument("--event", type=Path, default=DEFAULT_EVENT)
    analyze = commands.add_parser("analyze", help="analyze one simulated event")
    analyze.add_argument("--event", type=Path, default=DEFAULT_EVENT)
    analyze.add_argument("--provider")
    analyze.add_argument("--session-provider")
    analyze_handoff = commands.add_parser("analyze-handoff", help="analyze one already-frozen Event Handoff")
    analyze_handoff.add_argument("--handoff", type=Path, required=True)
    analyze_handoff.add_argument("--provider")
    analyze_handoff.add_argument("--session-provider")
    analyze_handoff.add_argument(
        "--reasoning",
        choices=sorted(DEEPSEEK_REASONING_EFFORTS),
        help="temporary DeepSeek reasoning effort override",
    )
    analyze_handoff.add_argument(
        "--action-policy",
        choices=sorted(ACTION_POLICY_MODES),
        help="temporary action decision policy mode override",
    )
    analyze_handoff.add_argument(
        "--force",
        action="store_true",
        help="force a new analysis even when an identical successful request exists",
    )
    decision = commands.add_parser("decision", help="manually review an existing AI Decision")
    decision_commands = decision.add_subparsers(dest="decision_command", required=True)
    accept = decision_commands.add_parser("accept", help="accept and prepare a manual V2A ACK file")
    accept.add_argument("--decision-id", required=True)
    accept.add_argument("--note")
    reject = decision_commands.add_parser("reject", help="reject without checkpoint or ACK")
    reject.add_argument("--decision-id", required=True)
    reject.add_argument("--reason")
    show = decision_commands.add_parser("show", help="show Decision, Job and human review status")
    show.add_argument("--decision-id", required=True)
    ack = commands.add_parser("ack", help="inspect the manual ACK outbox")
    ack_commands = ack.add_subparsers(dest="ack_command", required=True)
    ack_commands.add_parser("status", help="show NONE, PENDING or latest CONSUMED; read-only")
    consume = ack_commands.add_parser("consume", help="manually validate a V2A Receipt and clear its pending ACK")
    consume.add_argument("--receipt", type=Path, required=True)
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return command_doctor()
        if args.command == "providers":
            return command_providers()
        if args.command == "simulate":
            return command_simulate(args.event)
        if args.command == "analyze":
            return command_analyze(args.event, args.provider, args.session_provider)
        if args.command == "analyze-handoff":
            return command_analyze_handoff(
                args.handoff,
                args.provider,
                args.session_provider,
                args.reasoning,
                args.action_policy,
                args.force,
            )
        if args.command == "decision":
            manager = DecisionReviewManager(ROOT)
            if args.decision_command == "accept":
                result = manager.accept(args.decision_id, note=args.note)
            elif args.decision_command == "reject":
                result = manager.reject(args.decision_id, reason=args.reason)
            else:
                result = manager.show(args.decision_id)
            print_json(result)
            return 0
        if args.command == "ack":
            manager = AckReceiptManager(ROOT)
            print_json(manager.consume(args.receipt) if args.ack_command == "consume" else manager.status())
            return 0
    except CoordinatorError as error:
        output = {"status": "FAILED", "error_code": str(error.code), "message": error.message}
        reasoning_effort = reasoning_effort_for_error(args)
        if reasoning_effort is not None:
            output["reasoning_effort"] = reasoning_effort
            usage = error.usage_records[-1] if error.usage_records else {}
            output["latency_ms"] = usage.get("latency_ms")
            output["input_tokens"] = usage.get("input_tokens")
            output["output_tokens"] = usage.get("output_tokens")
            output["reasoning_tokens"] = usage.get("reasoning_tokens")
            output["total_tokens"] = usage.get("total_tokens")
        print_json(output)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
