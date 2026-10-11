#!/usr/bin/env python3
"""Command line interface for the paper Account Engine."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from engine import AccountEngine, EngineError


PROJECT_DIR = Path(__file__).resolve().parent


def add_order_arguments(parser: argparse.ArgumentParser, action: str) -> None:
    parser.add_argument("--order-id", required=True)
    parser.add_argument("--decision-id", required=True)
    parser.add_argument("--symbol", required=True)
    if action in {"BUY", "ADD", "REDUCE"}:
        size = parser.add_mutually_exclusive_group(required=True)
        size.add_argument("--qty", type=int)
        size.add_argument("--target-weight", help="例如 25%% 或 0.25；含义为成交后的目标持仓权重")
    price = parser.add_mutually_exclusive_group(required=action != "HOLD")
    price.add_argument("--reference-price")
    price.add_argument("--fill-price")
    parser.add_argument("--timestamp", help="ISO 8601；省略时使用 config.json 的时区当前时间")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--invalidation", default="", help="决策证伪条件")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A股/BSE 影子账户引擎")
    parser.add_argument("--data-dir", default=str(PROJECT_DIR / "data"), help="账户数据目录")
    parser.add_argument("--config", default=str(PROJECT_DIR / "config.json"), help="配置文件")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="初始化账户")
    init.add_argument("--date", required=True, help="首个交易日 YYYY-MM-DD")
    init.add_argument("--timestamp")
    init.add_argument("--initial-cash")

    sub.add_parser("status", help="输出当前派生账户状态")
    sub.add_parser("verify", help="只读校验账本、账户缓存和审计投影")
    report = sub.add_parser("report", help="生成完全离线的 account_report.html")
    report.add_argument("--output", help="输出路径；默认 data/account_report.html")
    rebuild = sub.add_parser("rebuild", help="从哈希链账本重建账户与缺失投影")
    rebuild.add_argument("--check-only", action="store_true", help="仅检查，不写回")

    for name, action in [("buy", "BUY"), ("add", "ADD"), ("reduce", "REDUCE"), ("exit", "EXIT"), ("hold", "HOLD")]:
        command = sub.add_parser(name, help=f"记录 {action} 指令")
        add_order_arguments(command, action)
        command.set_defaults(action=action)

    mark = sub.add_parser("mark", help="更新持仓估值价格，不改变数量/成本/已实现盈亏")
    mark.add_argument("--symbol", required=True)
    mark.add_argument("--price", required=True)
    mark.add_argument("--timestamp")

    new_day = sub.add_parser("new-day", help="进入新的交易日并按 T+1 解锁")
    new_day.add_argument("--date", required=True)
    new_day.add_argument("--timestamp")

    end_day = sub.add_parser("end-day", help="追加日终权益快照")
    end_day.add_argument("--timestamp")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        engine = AccountEngine(args.data_dir, args.config)
        if args.command == "init":
            result = engine.initialize(args.date, timestamp=args.timestamp, initial_cash=args.initial_cash)
        elif args.command == "status":
            result = engine.status()
        elif args.command == "verify":
            result = engine.verify()
        elif args.command == "report":
            result = engine.generate_report(args.output)
        elif args.command == "rebuild":
            result = engine.rebuild(check_only=args.check_only)
        elif args.command in {"buy", "add", "reduce", "exit", "hold"}:
            result = engine.submit_order(
                args.action,
                order_id=args.order_id,
                decision_id=args.decision_id,
                symbol=args.symbol,
                qty=getattr(args, "qty", None),
                target_weight=getattr(args, "target_weight", None),
                reference_price=args.reference_price,
                fill_price=args.fill_price,
                timestamp=args.timestamp,
                reason=args.reason,
                invalidation_condition=args.invalidation,
            )
        elif args.command == "mark":
            result = engine.mark_price(args.symbol, args.price, timestamp=args.timestamp)
        elif args.command == "new-day":
            result = engine.new_trading_day(args.date, timestamp=args.timestamp)
        elif args.command == "end-day":
            result = engine.end_day(timestamp=args.timestamp)
        else:
            raise AssertionError(args.command)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        if args.command == "rebuild" and args.check_only and result["status"] == "CHECK_FAILED":
            return 3
        if args.command == "verify" and result["status"] != "OK":
            return 3
        return 0
    except EngineError as exc:
        print(json.dumps({"status": "ERROR", "error_code": exc.code, "message": exc.message}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"status": "ERROR", "error_code": "INTERRUPTED", "message": "操作已中断"}, ensure_ascii=False), file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
