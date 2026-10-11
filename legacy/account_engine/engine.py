"""Auditable A-share/BSE paper-account engine.

The hash-chained ``account_events.jsonl`` journal is the sole source of truth.
``account.json`` and the other logs are rebuildable projections.
Only Python's standard library is used.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
from zoneinfo import ZoneInfo

from reporting import render_account_report


ZERO = Decimal("0")
MONEY_UNIT = Decimal("0.01")
CALC_UNIT = Decimal("0.00000001")
ZERO_HASH = "0" * 64


class EngineError(Exception):
    """Base error with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class OrderReject(EngineError):
    """A business-rule rejection that must be recorded in the ledger."""


class IntegrityError(EngineError):
    """Raised when the ledger or derived state is inconsistent."""


def dec(value: Any, field: str = "value") -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise EngineError("INVALID_DECIMAL", f"{field} 不是有效数字: {value!r}") from exc
    if not result.is_finite():
        raise EngineError("INVALID_DECIMAL", f"{field} 必须是有限数字")
    return result


def money(value: Any) -> Decimal:
    return dec(value).quantize(MONEY_UNIT, rounding=ROUND_HALF_UP)


def calc(value: Any) -> Decimal:
    return dec(value).quantize(CALC_UNIT, rounding=ROUND_HALF_UP)


def ds(value: Decimal, unit: Optional[Decimal] = None) -> str:
    if unit is not None:
        value = value.quantize(unit, rounding=ROUND_HALF_UP)
    return format(value, "f")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def object_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_target_weight(value: Any) -> Decimal:
    if value is None:
        raise EngineError("MISSING_TARGET_WEIGHT", "缺少目标仓位")
    text = str(value).strip()
    if text.endswith("%"):
        result = dec(text[:-1], "target_weight") / Decimal("100")
    else:
        result = dec(text, "target_weight")
    if result < ZERO or result > Decimal("1"):
        raise EngineError("INVALID_TARGET_WEIGHT", "target_weight 必须在 0% 到 100% 之间")
    return calc(result)


class FileLock:
    """Small cross-platform exclusive lock using only the standard library."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        if os.name == "nt":
            import msvcrt

            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.handle is None:
            return
        if os.name == "nt":
            import msvcrt

            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


class AccountEngine:
    ORDER_EVENT = "ORDER_PROCESSED"
    EVENT_FILE = "account_events.jsonl"
    ACCOUNT_FILE = "account.json"
    ORDER_FILE = "orders.jsonl"
    TRADE_FILE = "trades.jsonl"
    DECISION_FILE = "decision_log.jsonl"
    DAILY_FILE = "daily_equity.csv"

    DAILY_FIELDS = [
        "event_id",
        "date",
        "timestamp",
        "cash",
        "market_value",
        "total_equity",
        "positions_json",
        "daily_realized_pnl",
        "realized_pnl",
        "unrealized_pnl",
        "daily_return",
        "cumulative_return",
        "drawdown",
        "max_drawdown",
    ]

    def __init__(self, data_dir: Path | str, config_path: Path | str):
        self.data_dir = Path(data_dir).resolve()
        self.config_path = Path(config_path).resolve()
        self.config = self._load_config()
        self.zone = ZoneInfo(self.config["timezone"])
        self.lock_path = self.data_dir / ".account_engine.lock"

    def _load_config(self) -> Dict[str, Any]:
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise EngineError("CONFIG_NOT_FOUND", f"配置文件不存在: {self.config_path}") from exc
        except json.JSONDecodeError as exc:
            raise EngineError("CONFIG_INVALID", f"配置文件不是有效 JSON: {exc}") from exc
        required = ["initial_cash", "timezone", "fees", "execution_policies", "market_rules", "symbol_market_patterns", "trading_calendar"]
        missing = [key for key in required if key not in config]
        if missing:
            raise EngineError("CONFIG_INVALID", f"配置缺少字段: {', '.join(missing)}")
        if dec(config["initial_cash"], "initial_cash") <= ZERO:
            raise EngineError("CONFIG_INVALID", "initial_cash 必须大于 0")
        tick = dec(config.get("price_tick", "0.01"), "price_tick")
        if tick <= ZERO:
            raise EngineError("CONFIG_INVALID", "price_tick 必须大于 0")
        fee_fields = ["commission_rate", "minimum_commission", "stamp_duty_sell_rate", "transfer_fee_rate", "slippage_rate"]
        for field in fee_fields:
            if dec(config["fees"].get(field, "0"), field) < ZERO:
                raise EngineError("CONFIG_INVALID", f"{field} 不得为负")
        if dec(config["fees"].get("slippage_rate", "0")) >= Decimal("1"):
            raise EngineError("CONFIG_INVALID", "slippage_rate 必须小于 1")
        policies = config["execution_policies"]
        if policies.get("sell_shortfall", "reject") not in {"reject", "execute_available"}:
            raise EngineError("CONFIG_INVALID", "sell_shortfall 只能是 reject 或 execute_available")
        if policies.get("target_weight_cash_shortfall", "cap_to_affordable") not in {"reject", "cap_to_affordable"}:
            raise EngineError("CONFIG_INVALID", "target_weight_cash_shortfall 只能是 reject 或 cap_to_affordable")
        for market, rule in config["market_rules"].items():
            for field in ("min_buy_qty", "buy_step_qty", "min_sell_qty", "sell_step_qty"):
                if not isinstance(rule.get(field), int) or rule[field] <= 0:
                    raise EngineError("CONFIG_INVALID", f"{market}.{field} 必须是正整数")
        for entry in config["symbol_market_patterns"]:
            try:
                re.compile(entry["pattern"])
            except (KeyError, re.error) as exc:
                raise EngineError("CONFIG_INVALID", f"symbol_market_patterns 配置错误: {entry}") from exc
            if entry.get("market") not in config["market_rules"]:
                raise EngineError("CONFIG_INVALID", f"代码映射引用了未知市场: {entry.get('market')}")
        return config

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with FileLock(self.lock_path):
            yield

    @property
    def event_path(self) -> Path:
        return self.data_dir / self.EVENT_FILE

    @property
    def account_path(self) -> Path:
        return self.data_dir / self.ACCOUNT_FILE

    def _now(self) -> datetime:
        return datetime.now(self.zone).replace(microsecond=0)

    def _normalize_timestamp(
        self,
        value: Optional[str],
        *,
        default_date: Optional[str] = None,
        default_clock: time = time(12, 0),
    ) -> str:
        if value:
            text = value.strip().replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError as exc:
                raise EngineError("INVALID_TIMESTAMP", f"时间戳格式错误: {value}") from exc
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=self.zone)
            parsed = parsed.astimezone(self.zone)
        elif default_date:
            parsed = datetime.combine(date.fromisoformat(default_date), default_clock, tzinfo=self.zone)
        else:
            parsed = self._now()
        return parsed.replace(microsecond=0).isoformat()

    def _timestamp_date(self, timestamp: str) -> str:
        return datetime.fromisoformat(timestamp).astimezone(self.zone).date().isoformat()

    def _is_trading_day(self, day: str) -> bool:
        try:
            parsed = date.fromisoformat(day)
        except ValueError as exc:
            raise EngineError("INVALID_DATE", f"日期格式错误: {day}") from exc
        calendar = self.config["trading_calendar"]
        if day in set(calendar.get("extra_trading_days", [])):
            return True
        if day in set(calendar.get("holidays", [])):
            return False
        mode = calendar.get("mode", "weekday_with_holidays")
        if mode != "weekday_with_holidays":
            raise EngineError("CONFIG_INVALID", f"不支持的 trading_calendar.mode: {mode}")
        return parsed.weekday() < 5

    def _config_hash(self) -> str:
        return object_hash(self.config)

    def initialize(
        self,
        trading_date: str,
        *,
        timestamp: Optional[str] = None,
        initial_cash: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if not self._is_trading_day(trading_date):
            raise EngineError("NON_TRADING_DAY", f"{trading_date} 不是配置允许的交易日")
        ts = self._normalize_timestamp(timestamp, default_date=trading_date, default_clock=time(9, 0))
        if self._timestamp_date(ts) != trading_date:
            raise EngineError("DATE_TIMESTAMP_MISMATCH", "初始化日期与时间戳所属日期不一致")
        start_cash = money(initial_cash if initial_cash is not None else self.config["initial_cash"])
        if start_cash <= ZERO:
            raise EngineError("INVALID_INITIAL_CASH", "初始资金必须大于 0")
        with self._locked():
            if self.event_path.exists() and self.event_path.stat().st_size > 0:
                raise EngineError("ALREADY_INITIALIZED", f"账户目录已经初始化: {self.data_dir}")
            self.data_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "account_id": str(uuid.uuid4()),
                "initial_cash": ds(start_cash, MONEY_UNIT),
                "trading_date": trading_date,
                "config_hash": self._config_hash(),
                "config_version": self.config.get("config_version", 1),
            }
            event = self._append_event("ACCOUNT_INITIALIZED", payload, ts, [])
            events = [event]
            state = self._replay(events)
            self._ensure_projection_files()
            self._sync_all_projections(events)
            self._write_account(state)
            self._write_report(events, state)
            return {"status": "INITIALIZED", "event_id": event["event_id"], "account": state}

    def status(self) -> Dict[str, Any]:
        with self._locked():
            events, state, recovered = self._load_authoritative(recover_cache=True)
            self._sync_all_projections(events)
            return {"status": "OK", "state_recovered": recovered, "account": state}

    def verify(self) -> Dict[str, Any]:
        with self._locked():
            events = self._read_events()
            state = self._replay(events)
            self._check_invariants(state)
            cache_matches = False
            try:
                cached = json.loads(self.account_path.read_text(encoding="utf-8"))
                cache_matches = cached == state
            except (FileNotFoundError, json.JSONDecodeError):
                cache_matches = False
            projection_report = self._projection_report(events)
            return {
                "status": "OK" if cache_matches and projection_report["complete"] else "MISMATCH",
                "ledger_events": len(events),
                "last_event_hash": state["last_event_hash"],
                "account_cache_matches": cache_matches,
                "projections": projection_report,
            }

    def generate_report(self, output_path: Optional[Path | str] = None) -> Dict[str, Any]:
        """Build a self-contained HTML report without changing account facts."""
        with self._locked():
            events = self._read_events()
            state = self._replay(events)
            return self._write_report(events, state, output_path)

    def _write_report(
        self,
        events: List[Dict[str, Any]],
        state: Dict[str, Any],
        output_path: Optional[Path | str] = None,
    ) -> Dict[str, Any]:
        """Write the derived HTML report. Caller holds the account lock."""
        generated_at = self._now().isoformat()
        html = render_account_report(state, events, generated_at)
        target = Path(output_path).expanduser().resolve() if output_path else (self.data_dir / "account_report.html")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="account_report.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(html)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return {
            "status": "REPORT_GENERATED",
            "output": str(target),
            "size_bytes": target.stat().st_size,
            "generated_at": generated_at,
            "ledger_events": len(events),
            "account_last_event_hash": state["last_event_hash"],
        }

    def rebuild(self, *, check_only: bool = False) -> Dict[str, Any]:
        with self._locked():
            events = self._read_events()
            state = self._replay(events)
            before_matches = False
            try:
                before_matches = json.loads(self.account_path.read_text(encoding="utf-8")) == state
            except (FileNotFoundError, json.JSONDecodeError):
                before_matches = False
            projection_before = self._projection_report(events)
            if not check_only:
                if projection_before["complete"]:
                    self._sync_all_projections(events)
                else:
                    self._rebuild_projections(events)
                self._write_account(state)
            return {
                "status": "MATCHED" if before_matches and projection_before["complete"] else ("CHECK_FAILED" if check_only else "REBUILT"),
                "check_only": check_only,
                "account_matched_before": before_matches,
                "projections_complete_before": projection_before["complete"],
                "ledger_events": len(events),
                "last_event_hash": state["last_event_hash"],
            }

    def submit_order(
        self,
        action: str,
        *,
        order_id: str,
        decision_id: str,
        symbol: str,
        qty: Optional[int] = None,
        target_weight: Optional[Any] = None,
        reference_price: Optional[Any] = None,
        fill_price: Optional[Any] = None,
        timestamp: Optional[str] = None,
        reason: str,
        invalidation_condition: str = "",
    ) -> Dict[str, Any]:
        action = action.upper().strip()
        symbol = symbol.strip().upper()
        if action not in {"BUY", "ADD", "REDUCE", "EXIT", "HOLD"}:
            raise EngineError("INVALID_ACTION", f"不支持的指令: {action}")
        if not order_id.strip():
            raise EngineError("MISSING_ORDER_ID", "order_id 不能为空")
        if not decision_id.strip():
            raise EngineError("MISSING_DECISION_ID", "decision_id 不能为空")
        if not symbol:
            raise EngineError("MISSING_SYMBOL", "symbol 不能为空")
        if not reason.strip():
            raise EngineError("MISSING_REASON", "reason 不能为空")
        if qty is not None and (not isinstance(qty, int) or qty <= 0):
            raise EngineError("INVALID_QTY", "qty 必须是正整数")
        if target_weight is not None:
            normalized_weight = parse_target_weight(target_weight)
        else:
            normalized_weight = None
        if action in {"BUY", "ADD", "REDUCE"}:
            if (qty is None) == (normalized_weight is None):
                raise EngineError("QTY_TARGET_EXCLUSIVE", "qty 与 target_weight 必须且只能提供一个")
        elif action in {"EXIT", "HOLD"} and (qty is not None or normalized_weight is not None):
            raise EngineError("UNEXPECTED_SIZE", f"{action} 不接受 qty 或 target_weight")
        if reference_price is not None and fill_price is not None:
            raise EngineError("PRICE_EXCLUSIVE", "reference_price 与 fill_price 只能提供一个")
        if action != "HOLD" and reference_price is None and fill_price is None:
            raise EngineError("MISSING_PRICE", "交易指令必须提供 reference_price 或 fill_price")

        request_fingerprint_data = {
            "action": action,
            "decision_id": decision_id,
            "symbol": symbol,
            "requested_qty": qty,
            "requested_target_weight": ds(normalized_weight, CALC_UNIT) if normalized_weight is not None else None,
            "reference_price": str(reference_price) if reference_price is not None else None,
            "fill_price": str(fill_price) if fill_price is not None else None,
            "reason": reason,
            "invalidation_condition": invalidation_condition,
        }
        request_fingerprint = object_hash(request_fingerprint_data)

        with self._locked():
            events, state, recovered = self._load_authoritative(recover_cache=True)
            existing = self._find_order(events, order_id)
            if existing is not None:
                if existing.get("request_fingerprint") != request_fingerprint:
                    raise EngineError(
                        "DUPLICATE_ORDER_CONFLICT",
                        f"order_id={order_id} 已存在，但本次参数与原订单不一致；未再次记账",
                    )
                result = copy.deepcopy(existing)
                result["duplicate"] = True
                result["state_recovered"] = recovered
                return result

            ts = self._normalize_timestamp(timestamp)
            if self._timestamp_date(ts) != state["current_trading_date"]:
                raise EngineError(
                    "DATE_TIMESTAMP_MISMATCH",
                    f"订单时间属于 {self._timestamp_date(ts)}，当前账户交易日为 {state['current_trading_date']}；请先执行 new-day",
                )
            self._assert_monotonic_timestamp(events, ts)

            before = copy.deepcopy(state)
            market, rule = self._resolve_market(symbol)
            order: Dict[str, Any]
            trade: Optional[Dict[str, Any]] = None
            try:
                if state["day_closed"]:
                    raise OrderReject("DAY_CLOSED", "当前交易日已经 end-day，不能再执行交易指令")
                if action == "HOLD":
                    order = self._base_order(
                        before,
                        action,
                        order_id,
                        decision_id,
                        ts,
                        symbol,
                        market,
                        qty,
                        normalized_weight,
                        reference_price,
                        fill_price,
                        reason,
                        invalidation_condition,
                        request_fingerprint,
                    )
                    order.update({"side": "HOLD", "status": "HELD", "reject_code": None, "reject_reason": None})
                    self._add_after_fields(order, before, symbol)
                else:
                    order, trade, state = self._prepare_trade(
                        before,
                        action,
                        order_id,
                        decision_id,
                        ts,
                        symbol,
                        market,
                        rule,
                        qty,
                        normalized_weight,
                        reference_price,
                        fill_price,
                        reason,
                        invalidation_condition,
                        request_fingerprint,
                    )
            except OrderReject as rejection:
                state = before
                order = self._base_order(
                    before,
                    action,
                    order_id,
                    decision_id,
                    ts,
                    symbol,
                    market,
                    qty,
                    normalized_weight,
                    reference_price,
                    fill_price,
                    reason,
                    invalidation_condition,
                    request_fingerprint,
                )
                order.update(
                    {
                        "side": "BUY" if action in {"BUY", "ADD"} else ("SELL" if action in {"REDUCE", "EXIT"} else "HOLD"),
                        "status": "REJECTED",
                        "reject_code": rejection.code,
                        "reject_reason": rejection.message,
                    }
                )
                self._add_after_fields(order, before, symbol)

            decision = {
                "decision_id": decision_id,
                "order_id": order_id,
                "timestamp": ts,
                "trading_date": state["current_trading_date"],
                "symbol": symbol,
                "action": action,
                "reason": reason,
                "invalidation_condition": invalidation_condition,
                "order_status": order["status"],
                "reject_reason": order.get("reject_reason"),
            }
            payload = {
                "order": order,
                "trade": trade,
                "decision": decision,
                "config_hash": self._config_hash(),
            }
            event = self._append_event(self.ORDER_EVENT, payload, ts, events)
            events.append(event)
            authoritative = self._replay(events)
            self._sync_projection_event(event)
            self._write_account(authoritative)
            self._write_report(events, authoritative)
            result = copy.deepcopy(order)
            result["event_id"] = event["event_id"]
            result["duplicate"] = False
            result["state_recovered"] = recovered
            return result

    def mark_price(self, symbol: str, price: Any, *, timestamp: Optional[str] = None) -> Dict[str, Any]:
        symbol = symbol.strip().upper()
        with self._locked():
            events, state, recovered = self._load_authoritative(recover_cache=True)
            ts = self._normalize_timestamp(timestamp)
            self._assert_current_open_day(state, events, ts)
            mark = self._validated_market_price(price, "price")
            market, _ = self._resolve_market(symbol)
            payload = {
                "symbol": symbol,
                "market": market,
                "price": ds(mark, Decimal(self.config.get("price_tick", "0.01"))),
                "config_hash": self._config_hash(),
            }
            event = self._append_event("MARK_PRICE", payload, ts, events)
            events.append(event)
            rebuilt = self._replay(events)
            self._write_account(rebuilt)
            self._write_report(events, rebuilt)
            return {
                "status": "MARKED",
                "event_id": event["event_id"],
                "symbol": symbol,
                "price": payload["price"],
                "state_recovered": recovered,
                "account": rebuilt,
            }

    def new_trading_day(self, trading_date: str, *, timestamp: Optional[str] = None) -> Dict[str, Any]:
        if not self._is_trading_day(trading_date):
            raise EngineError("NON_TRADING_DAY", f"{trading_date} 不是配置允许的交易日，T+1 不解锁")
        ts = self._normalize_timestamp(timestamp, default_date=trading_date, default_clock=time(9, 0))
        if self._timestamp_date(ts) != trading_date:
            raise EngineError("DATE_TIMESTAMP_MISMATCH", "new-day 日期与时间戳所属日期不一致")
        with self._locked():
            events, state, recovered = self._load_authoritative(recover_cache=True)
            self._assert_monotonic_timestamp(events, ts)
            if date.fromisoformat(trading_date) <= date.fromisoformat(state["current_trading_date"]):
                raise EngineError("DATE_NOT_FORWARD", "new-day 必须进入晚于当前交易日的日期")
            if self.config["execution_policies"].get("require_end_day_before_new_day", True) and not state["day_closed"]:
                raise EngineError("PREVIOUS_DAY_NOT_CLOSED", "上一交易日尚未执行 end-day")
            unlocked: Dict[str, int] = {}
            for symbol, position in state["positions"].items():
                qty = sum(int(lot["qty"]) for lot in position["t1_lots"] if lot["buy_date"] < trading_date)
                if qty:
                    unlocked[symbol] = qty
            payload = {
                "from_date": state["current_trading_date"],
                "trading_date": trading_date,
                "unlocked_by_symbol": unlocked,
                "config_hash": self._config_hash(),
            }
            event = self._append_event("TRADING_DAY_STARTED", payload, ts, events)
            events.append(event)
            rebuilt = self._replay(events)
            self._write_account(rebuilt)
            self._write_report(events, rebuilt)
            return {
                "status": "NEW_TRADING_DAY",
                "event_id": event["event_id"],
                "trading_date": trading_date,
                "unlocked_by_symbol": unlocked,
                "state_recovered": recovered,
                "account": rebuilt,
            }

    def end_day(self, *, timestamp: Optional[str] = None) -> Dict[str, Any]:
        with self._locked():
            events, state, recovered = self._load_authoritative(recover_cache=True)
            ts = self._normalize_timestamp(timestamp, default_date=state["current_trading_date"], default_clock=time(15, 5))
            self._assert_current_open_day(state, events, ts)
            previous = self._last_daily_snapshot(events)
            previous_equity = dec(previous["total_equity"]) if previous else dec(state["initial_cash"])
            previous_realized = dec(previous["realized_pnl"]) if previous else ZERO
            equity = dec(state["total_equity"])
            daily_return = calc(equity / previous_equity - Decimal("1")) if previous_equity else ZERO
            cumulative_return = calc(equity / dec(state["initial_cash"]) - Decimal("1"))
            positions = {
                symbol: {
                    "position_qty": position["position_qty"],
                    "sellable_qty": position["sellable_qty"],
                    "locked_t1_qty": position["locked_t1_qty"],
                    "average_cost": position["average_cost"],
                    "last_price": position["last_price"],
                    "market_value": position["market_value"],
                    "unrealized_pnl": position["unrealized_pnl"],
                }
                for symbol, position in state["positions"].items()
                if int(position["position_qty"]) > 0
            }
            snapshot = {
                "date": state["current_trading_date"],
                "timestamp": ts,
                "cash": state["cash"],
                "market_value": state["market_value"],
                "total_equity": state["total_equity"],
                "positions": positions,
                "daily_realized_pnl": ds(calc(dec(state["realized_pnl"]) - previous_realized), CALC_UNIT),
                "realized_pnl": state["realized_pnl"],
                "unrealized_pnl": state["unrealized_pnl"],
                "daily_return": ds(daily_return, CALC_UNIT),
                "cumulative_return": ds(cumulative_return, CALC_UNIT),
                "drawdown": state["drawdown"],
                "max_drawdown": state["max_drawdown"],
            }
            event = self._append_event("DAY_ENDED", {"snapshot": snapshot}, ts, events)
            events.append(event)
            rebuilt = self._replay(events)
            self._sync_projection_event(event)
            self._write_account(rebuilt)
            self._write_report(events, rebuilt)
            result = copy.deepcopy(snapshot)
            result.update({"status": "DAY_ENDED", "event_id": event["event_id"], "state_recovered": recovered})
            return result

    def _prepare_trade(
        self,
        before: Dict[str, Any],
        action: str,
        order_id: str,
        decision_id: str,
        timestamp: str,
        symbol: str,
        market: str,
        rule: Dict[str, Any],
        qty: Optional[int],
        target_weight: Optional[Decimal],
        reference_price: Optional[Any],
        direct_fill_price: Optional[Any],
        reason: str,
        invalidation_condition: str,
        request_fingerprint: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        position = self._get_position(before, symbol, market)
        position_qty = int(position["position_qty"])
        if self.config["execution_policies"].get("strict_action_semantics", True):
            if action == "BUY" and position_qty != 0:
                raise OrderReject("BUY_REQUIRES_FLAT", "BUY 仅用于空仓首次建立；已有持仓请使用 ADD")
            if action == "ADD" and position_qty == 0:
                raise OrderReject("ADD_REQUIRES_POSITION", "ADD 需要已有持仓；空仓请使用 BUY")
            if action in {"REDUCE", "EXIT"} and position_qty == 0:
                raise OrderReject("NO_POSITION", "当前没有可减仓/清仓的持仓")

        side = "BUY" if action in {"BUY", "ADD"} else "SELL"
        reference = self._validated_market_price(reference_price, "reference_price") if reference_price is not None else None
        fill = self._derive_fill_price(side, reference, direct_fill_price)
        valuation_price = reference if reference is not None else fill
        target_equity_basis = self._equity_with_symbol_price(before, symbol, valuation_price)
        requested_trade_qty: int
        calculated_qty: Optional[int] = None
        status = "FILLED"

        if side == "BUY":
            if qty is not None:
                self._validate_buy_qty(qty, rule)
                requested_trade_qty = qty
            else:
                assert target_weight is not None
                target_value = target_equity_basis * target_weight
                desired_total = self._round_buy_down(int((target_value / valuation_price).to_integral_value(rounding=ROUND_DOWN)), rule)
                if desired_total <= position_qty:
                    raise OrderReject("TARGET_NOT_ABOVE_CURRENT", "目标仓位不高于当前持仓，不能执行 BUY/ADD")
                requested_trade_qty = desired_total - position_qty
                requested_trade_qty = self._round_buy_down(requested_trade_qty, rule)
                calculated_qty = requested_trade_qty
                if requested_trade_qty <= 0:
                    raise OrderReject("TARGET_BELOW_MINIMUM", "目标仓位对应数量低于最小买入单位")
            fees = self._calculate_fees("BUY", money(fill * requested_trade_qty))
            needed = money(fill * requested_trade_qty) + dec(fees["total"])
            cash = dec(before["cash"])
            executed_qty = requested_trade_qty
            if needed > cash:
                if qty is not None or self.config["execution_policies"].get("target_weight_cash_shortfall", "cap_to_affordable") == "reject":
                    raise OrderReject("INSUFFICIENT_CASH", f"可用现金 {before['cash']}，所需现金 {ds(needed, MONEY_UNIT)}")
                executed_qty = self._max_affordable_buy_qty(cash, fill, requested_trade_qty, rule)
                if executed_qty <= 0:
                    raise OrderReject("INSUFFICIENT_CASH", "可用现金不足以完成最小交易单位的买入")
                status = "PARTIALLY_FILLED"
            gross = money(fill * executed_qty)
            fees = self._calculate_fees("BUY", gross)
        else:
            sellable = int(position["sellable_qty"])
            if action == "EXIT":
                requested_trade_qty = position_qty
            elif qty is not None:
                self._validate_sell_qty(qty, position_qty, rule)
                requested_trade_qty = qty
            else:
                assert target_weight is not None
                current_value = valuation_price * position_qty
                target_value = target_equity_basis * target_weight
                if target_value >= current_value:
                    raise OrderReject("TARGET_NOT_BELOW_CURRENT", "目标仓位不低于当前持仓，不能执行 REDUCE")
                raw_target_qty = int((target_value / valuation_price).to_integral_value(rounding=ROUND_UP)) if target_weight > ZERO else 0
                desired_remaining = self._round_holding_up(raw_target_qty, rule) if raw_target_qty else 0
                desired_remaining = min(desired_remaining, position_qty)
                requested_trade_qty = position_qty - desired_remaining
                requested_trade_qty = self._round_sell_down(requested_trade_qty, position_qty, rule)
                calculated_qty = requested_trade_qty
                if requested_trade_qty <= 0:
                    raise OrderReject("TARGET_CHANGE_BELOW_MINIMUM", "目标仓位变化不足一个合法卖出单位")
            if requested_trade_qty > sellable:
                policy = self.config["execution_policies"].get("sell_shortfall", "reject")
                if policy != "execute_available":
                    raise OrderReject(
                        "T1_SELLABLE_LIMIT",
                        f"请求卖出 {requested_trade_qty} 股，但可卖仅 {sellable} 股（持仓 {position_qty}，T+1 锁定 {position['locked_t1_qty']}）",
                    )
                executed_qty = self._round_sell_down(sellable, position_qty, rule)
                if executed_qty <= 0:
                    raise OrderReject("T1_SELLABLE_LIMIT", "没有满足市场单位规则的可卖数量")
                status = "PARTIALLY_FILLED"
            else:
                executed_qty = requested_trade_qty
            self._validate_sell_qty(executed_qty, position_qty, rule)
            gross = money(fill * executed_qty)
            fees = self._calculate_fees("SELL", gross)

        total_fees = dec(fees["total"])
        net_cash_change = money(-(gross + total_fees) if side == "BUY" else gross - total_fees)
        trade_id = f"TR-{order_id}"
        trade = {
            "trade_id": trade_id,
            "order_id": order_id,
            "decision_id": decision_id,
            "timestamp": timestamp,
            "trading_date": before["current_trading_date"],
            "symbol": symbol,
            "market": market,
            "side": side,
            "executed_qty": executed_qty,
            "reference_price": ds(reference, Decimal(self.config.get("price_tick", "0.01"))) if reference is not None else None,
            "fill_price": ds(fill, Decimal(self.config.get("price_tick", "0.01"))),
            "gross_amount": ds(gross, MONEY_UNIT),
            "fees": fees,
            "net_cash_change": ds(net_cash_change, MONEY_UNIT),
            "position_before": position_qty,
            "sellable_before": int(position["sellable_qty"]),
            "locked_t1_before": int(position["locked_t1_qty"]),
            "cash_before": before["cash"],
        }
        simulated = copy.deepcopy(before)
        self._apply_trade(simulated, trade, validate_after=False)
        after_position = simulated["positions"][symbol]
        trade.update(
            {
                "position_after": int(after_position["position_qty"]),
                "sellable_after": int(after_position["sellable_qty"]),
                "locked_t1_after": int(after_position["locked_t1_qty"]),
                "cash_after": simulated["cash"],
                "average_cost_after": after_position["average_cost"],
                "realized_pnl_delta": self._trade_realized_delta(before, simulated, symbol),
            }
        )
        order = self._base_order(
            before,
            action,
            order_id,
            decision_id,
            timestamp,
            symbol,
            market,
            qty,
            target_weight,
            reference_price,
            direct_fill_price,
            reason,
            invalidation_condition,
            request_fingerprint,
        )
        order.update(
            {
                "side": side,
                "calculated_qty": calculated_qty,
                "executed_qty": executed_qty,
                "reference_price": trade["reference_price"],
                "fill_price": trade["fill_price"],
                "gross_amount": trade["gross_amount"],
                "fees": fees,
                "net_cash_change": trade["net_cash_change"],
                "target_equity_basis": ds(money(target_equity_basis), MONEY_UNIT) if target_weight is not None else None,
                "actual_weight_after": self._actual_weight(simulated, symbol),
                "status": status,
                "reject_code": None,
                "reject_reason": None,
            }
        )
        self._add_after_fields(order, simulated, symbol)
        return order, trade, simulated

    def _base_order(
        self,
        state: Dict[str, Any],
        action: str,
        order_id: str,
        decision_id: str,
        timestamp: str,
        symbol: str,
        market: str,
        qty: Optional[int],
        target_weight: Optional[Decimal],
        reference_price: Optional[Any],
        fill_price: Optional[Any],
        reason: str,
        invalidation_condition: str,
        request_fingerprint: str,
    ) -> Dict[str, Any]:
        position = self._get_position(state, symbol, market)
        return {
            "order_id": order_id,
            "decision_id": decision_id,
            "timestamp": timestamp,
            "trading_date": state["current_trading_date"],
            "symbol": symbol,
            "market": market,
            "action": action,
            "side": None,
            "requested_target_weight": ds(target_weight, CALC_UNIT) if target_weight is not None else None,
            "requested_qty": qty,
            "calculated_qty": None,
            "executed_qty": 0,
            "reference_price": str(reference_price) if reference_price is not None else None,
            "fill_price": str(fill_price) if fill_price is not None else None,
            "gross_amount": "0.00",
            "fees": {"commission": "0.00", "stamp_duty": "0.00", "transfer_fee": "0.00", "total": "0.00"},
            "net_cash_change": "0.00",
            "target_equity_basis": None,
            "actual_weight_after": self._actual_weight(state, symbol),
            "position_before": int(position["position_qty"]),
            "sellable_before": int(position["sellable_qty"]),
            "locked_t1_before": int(position["locked_t1_qty"]),
            "cash_before": state["cash"],
            "reason": reason,
            "invalidation_condition": invalidation_condition,
            "status": None,
            "reject_code": None,
            "reject_reason": None,
            "request_fingerprint": request_fingerprint,
        }

    def _add_after_fields(self, order: Dict[str, Any], state: Dict[str, Any], symbol: str) -> None:
        market = order["market"]
        position = self._get_position(state, symbol, market)
        order.update(
            {
                "position_after": int(position["position_qty"]),
                "sellable_after": int(position["sellable_qty"]),
                "locked_t1_after": int(position["locked_t1_qty"]),
                "cash_after": state["cash"],
            }
        )

    def _validated_market_price(self, value: Any, field: str) -> Decimal:
        price = dec(value, field)
        tick = Decimal(self.config.get("price_tick", "0.01"))
        if price <= ZERO:
            raise EngineError("INVALID_PRICE", f"{field} 必须大于 0")
        if price.quantize(tick, rounding=ROUND_HALF_UP) != price:
            raise EngineError("INVALID_PRICE_TICK", f"{field}={price} 不符合价格最小变动单位 {tick}")
        return price

    def _derive_fill_price(self, side: str, reference: Optional[Decimal], direct_fill: Optional[Any]) -> Decimal:
        tick = Decimal(self.config.get("price_tick", "0.01"))
        if direct_fill is not None:
            return self._validated_market_price(direct_fill, "fill_price")
        assert reference is not None
        slippage = dec(self.config["fees"].get("slippage_rate", "0"), "slippage_rate")
        raw = reference * (Decimal("1") + slippage if side == "BUY" else Decimal("1") - slippage)
        rounding = ROUND_UP if side == "BUY" else ROUND_DOWN
        fill = raw.quantize(tick, rounding=rounding)
        if fill <= ZERO:
            raise OrderReject("INVALID_FILL_PRICE", "滑点计算后的成交价无效")
        return fill

    def _calculate_fees(self, side: str, gross: Decimal) -> Dict[str, str]:
        cfg = self.config["fees"]
        commission = gross * dec(cfg["commission_rate"], "commission_rate")
        minimum = dec(cfg["minimum_commission"], "minimum_commission")
        if commission > ZERO:
            commission = max(commission, minimum)
        commission = money(commission)
        stamp = money(gross * dec(cfg["stamp_duty_sell_rate"], "stamp_duty_sell_rate")) if side == "SELL" else ZERO
        apply_side = cfg.get("transfer_fee_apply", "both")
        transfer_applies = apply_side == "both" or apply_side.lower() == side.lower()
        transfer = money(gross * dec(cfg["transfer_fee_rate"], "transfer_fee_rate")) if transfer_applies else ZERO
        total = money(commission + stamp + transfer)
        return {
            "commission": ds(commission, MONEY_UNIT),
            "stamp_duty": ds(stamp, MONEY_UNIT),
            "transfer_fee": ds(transfer, MONEY_UNIT),
            "total": ds(total, MONEY_UNIT),
        }

    def _resolve_market(self, symbol: str) -> Tuple[str, Dict[str, Any]]:
        overrides = self.config.get("symbol_market_overrides", {})
        market = overrides.get(symbol)
        if market is None:
            for entry in self.config["symbol_market_patterns"]:
                if re.fullmatch(entry["pattern"], symbol):
                    market = entry["market"]
                    break
        if market is None or market not in self.config["market_rules"]:
            raise EngineError("UNKNOWN_MARKET", f"无法根据配置识别代码 {symbol} 的市场；请在 config.json 中增加映射")
        return market, self.config["market_rules"][market]

    def _validate_buy_qty(self, qty: int, rule: Dict[str, Any]) -> None:
        minimum, step = int(rule["min_buy_qty"]), int(rule["buy_step_qty"])
        if qty < minimum or (qty - minimum) % step != 0:
            raise OrderReject("INVALID_BUY_UNIT", f"买入数量 {qty} 不符合 min={minimum}, step={step}")

    def _validate_sell_qty(self, qty: int, position_qty: int, rule: Dict[str, Any]) -> None:
        if qty <= 0:
            raise OrderReject("INVALID_SELL_QTY", "卖出数量必须大于 0")
        if qty == position_qty and rule.get("allow_sell_all_odd_lot", True):
            return
        minimum, step = int(rule["min_sell_qty"]), int(rule["sell_step_qty"])
        if qty < minimum or (qty - minimum) % step != 0:
            raise OrderReject("INVALID_SELL_UNIT", f"卖出数量 {qty} 不符合 min={minimum}, step={step}；不足单位仅允许一次性卖出全部余股")

    def _round_buy_down(self, qty: int, rule: Dict[str, Any]) -> int:
        minimum, step = int(rule["min_buy_qty"]), int(rule["buy_step_qty"])
        if qty < minimum:
            return 0
        return minimum + ((qty - minimum) // step) * step

    def _round_holding_up(self, qty: int, rule: Dict[str, Any]) -> int:
        minimum, step = int(rule["min_buy_qty"]), int(rule["buy_step_qty"])
        if qty <= 0:
            return 0
        if qty <= minimum:
            return minimum
        return minimum + ((qty - minimum + step - 1) // step) * step

    def _round_sell_down(self, qty: int, position_qty: int, rule: Dict[str, Any]) -> int:
        if qty >= position_qty and rule.get("allow_sell_all_odd_lot", True):
            return position_qty
        minimum, step = int(rule["min_sell_qty"]), int(rule["sell_step_qty"])
        if qty < minimum:
            return 0
        return minimum + ((qty - minimum) // step) * step

    def _max_affordable_buy_qty(self, cash: Decimal, fill: Decimal, max_qty: int, rule: Dict[str, Any]) -> int:
        maximum = self._round_buy_down(max_qty, rule)
        minimum, step = int(rule["min_buy_qty"]), int(rule["buy_step_qty"])
        if maximum < minimum:
            return 0
        max_index = (maximum - minimum) // step
        low, high, best = 0, max_index, -1
        while low <= high:
            mid = (low + high) // 2
            candidate = minimum + mid * step
            gross = money(fill * candidate)
            cost = gross + dec(self._calculate_fees("BUY", gross)["total"])
            if cost <= cash:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        return 0 if best < 0 else minimum + best * step

    def _equity_with_symbol_price(self, state: Dict[str, Any], symbol: str, price: Decimal) -> Decimal:
        current_mv = ZERO
        position = state["positions"].get(symbol)
        if position:
            current_mv = dec(position["market_value"])
            replacement = money(price * int(position["position_qty"]))
        else:
            replacement = ZERO
        return money(dec(state["total_equity"]) - current_mv + replacement)

    def _actual_weight(self, state: Dict[str, Any], symbol: str) -> str:
        equity = dec(state["total_equity"])
        position = state["positions"].get(symbol)
        if equity <= ZERO or position is None:
            return "0.00000000"
        return ds(calc(dec(position["market_value"]) / equity), CALC_UNIT)

    def _trade_realized_delta(self, before: Dict[str, Any], after: Dict[str, Any], symbol: str) -> str:
        before_value = dec(before["positions"].get(symbol, {}).get("realized_pnl", "0"))
        after_value = dec(after["positions"][symbol]["realized_pnl"])
        return ds(calc(after_value - before_value), CALC_UNIT)

    def _empty_position(self, symbol: str, market: str) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "market": market,
            "position_qty": 0,
            "sellable_qty": 0,
            "locked_t1_qty": 0,
            "t1_lots": [],
            "cost_basis": "0.00000000",
            "average_cost": "0.00000000",
            "last_price": "0.00",
            "market_value": "0.00",
            "unrealized_pnl": "0.00000000",
            "realized_pnl": "0.00000000",
            "total_pnl": "0.00000000",
        }

    def _get_position(self, state: Dict[str, Any], symbol: str, market: str) -> Dict[str, Any]:
        return copy.deepcopy(state["positions"].get(symbol, self._empty_position(symbol, market)))

    def _apply_trade(self, state: Dict[str, Any], trade: Dict[str, Any], *, validate_after: bool = True) -> None:
        symbol, market = trade["symbol"], trade["market"]
        position = state["positions"].setdefault(symbol, self._empty_position(symbol, market))
        qty = int(trade["executed_qty"])
        fill = dec(trade["fill_price"])
        gross = money(fill * qty)
        if ds(gross, MONEY_UNIT) != trade["gross_amount"]:
            raise IntegrityError("TRADE_GROSS_MISMATCH", f"{trade['trade_id']} 成交金额不一致")
        fee_total = sum((dec(v) for k, v in trade["fees"].items() if k != "total"), ZERO)
        if money(fee_total) != money(trade["fees"]["total"]):
            raise IntegrityError("TRADE_FEE_MISMATCH", f"{trade['trade_id']} 费用合计不一致")
        if state["cash"] != trade["cash_before"]:
            raise IntegrityError("TRADE_CASH_BEFORE_MISMATCH", f"{trade['trade_id']} cash_before 不一致")
        if int(position["position_qty"]) != int(trade["position_before"]):
            raise IntegrityError("TRADE_POSITION_BEFORE_MISMATCH", f"{trade['trade_id']} position_before 不一致")

        old_qty = int(position["position_qty"])
        old_cost = dec(position["cost_basis"])
        fees = dec(trade["fees"]["total"])
        side = trade["side"]
        if side == "BUY":
            expected_cash_change = money(-(gross + fees))
            if dec(state["cash"]) + expected_cash_change < ZERO:
                raise IntegrityError("NEGATIVE_CASH", f"{trade['trade_id']} 会导致现金为负")
            new_qty = old_qty + qty
            new_cost = calc(old_cost + gross + fees)
            position["position_qty"] = new_qty
            position["locked_t1_qty"] = int(position["locked_t1_qty"]) + qty
            position["t1_lots"].append({"trade_id": trade["trade_id"], "buy_date": trade["trading_date"], "qty": qty})
            position["cost_basis"] = ds(new_cost, CALC_UNIT)
            position["average_cost"] = ds(calc(new_cost / new_qty), CALC_UNIT)
        elif side == "SELL":
            if qty > int(position["sellable_qty"]):
                raise IntegrityError("T1_SELLABLE_LIMIT", f"{trade['trade_id']} 卖出超过可卖数量")
            if qty > old_qty:
                raise IntegrityError("NEGATIVE_POSITION", f"{trade['trade_id']} 卖出超过持仓")
            expected_cash_change = money(gross - fees)
            allocated_cost = calc(old_cost * Decimal(qty) / Decimal(old_qty))
            realized_delta = calc(expected_cash_change - allocated_cost)
            new_qty = old_qty - qty
            position["position_qty"] = new_qty
            position["sellable_qty"] = int(position["sellable_qty"]) - qty
            position["realized_pnl"] = ds(calc(dec(position["realized_pnl"]) + realized_delta), CALC_UNIT)
            if new_qty == 0:
                position["cost_basis"] = "0.00000000"
                position["average_cost"] = "0.00000000"
            else:
                remaining_cost = calc(old_cost - allocated_cost)
                position["cost_basis"] = ds(remaining_cost, CALC_UNIT)
                position["average_cost"] = ds(calc(remaining_cost / new_qty), CALC_UNIT)
        else:
            raise IntegrityError("INVALID_TRADE_SIDE", f"未知成交方向: {side}")

        if ds(expected_cash_change, MONEY_UNIT) != trade["net_cash_change"]:
            raise IntegrityError("TRADE_CASH_CHANGE_MISMATCH", f"{trade['trade_id']} net_cash_change 不一致")
        state["cash"] = ds(money(dec(state["cash"]) + expected_cash_change), MONEY_UNIT)
        mark = trade["reference_price"] if trade.get("reference_price") is not None else trade["fill_price"]
        position["last_price"] = str(mark)
        self._recalculate(state, update_peak=True)
        if validate_after:
            checks = {
                "position_after": int(position["position_qty"]),
                "sellable_after": int(position["sellable_qty"]),
                "locked_t1_after": int(position["locked_t1_qty"]),
                "cash_after": state["cash"],
                "average_cost_after": position["average_cost"],
            }
            for field, actual in checks.items():
                if actual != trade[field]:
                    raise IntegrityError("TRADE_AFTER_MISMATCH", f"{trade['trade_id']} {field} 不一致")
        self._check_invariants(state)

    def _recalculate(self, state: Dict[str, Any], *, update_peak: bool) -> None:
        market_value = ZERO
        realized = ZERO
        unrealized = ZERO
        for position in state["positions"].values():
            qty = int(position["position_qty"])
            mv = money(dec(position["last_price"]) * qty)
            upnl = calc(mv - dec(position["cost_basis"]))
            position["market_value"] = ds(mv, MONEY_UNIT)
            position["unrealized_pnl"] = ds(upnl, CALC_UNIT)
            position["total_pnl"] = ds(calc(dec(position["realized_pnl"]) + upnl), CALC_UNIT)
            market_value += mv
            realized += dec(position["realized_pnl"])
            unrealized += upnl
        equity = money(dec(state["cash"]) + market_value)
        state["market_value"] = ds(money(market_value), MONEY_UNIT)
        state["total_equity"] = ds(equity, MONEY_UNIT)
        state["realized_pnl"] = ds(calc(realized), CALC_UNIT)
        state["unrealized_pnl"] = ds(calc(unrealized), CALC_UNIT)
        state["total_pnl"] = ds(calc(realized + unrealized), CALC_UNIT)
        peak = dec(state["peak_equity"])
        if update_peak and equity > peak:
            peak = equity
            state["peak_equity"] = ds(peak, MONEY_UNIT)
        drawdown = calc(equity / peak - Decimal("1")) if peak > ZERO else ZERO
        state["drawdown"] = ds(drawdown, CALC_UNIT)
        state["max_drawdown"] = ds(min(dec(state["max_drawdown"]), drawdown), CALC_UNIT)

    def _check_invariants(self, state: Dict[str, Any]) -> None:
        errors: List[str] = []
        if dec(state["cash"]) < ZERO:
            errors.append("cash < 0")
        if dec(state["peak_equity"]) < dec(state["total_equity"]):
            errors.append("peak_equity < total_equity")
        expected_drawdown = calc(dec(state["total_equity"]) / dec(state["peak_equity"]) - Decimal("1"))
        if dec(state["drawdown"]) != expected_drawdown:
            errors.append("drawdown 与 total_equity / peak_equity - 1 不一致")
        if dec(state["max_drawdown"]) > dec(state["drawdown"]):
            errors.append("max_drawdown 大于当前 drawdown")
        equity_pnl = calc(dec(state["total_equity"]) - dec(state["initial_cash"]))
        if equity_pnl != dec(state["total_pnl"]):
            errors.append("total_pnl 与 total_equity - initial_cash 不一致")
        for symbol, position in state["positions"].items():
            qty = int(position["position_qty"])
            sellable = int(position["sellable_qty"])
            locked = int(position["locked_t1_qty"])
            lot_sum = sum(int(lot["qty"]) for lot in position["t1_lots"])
            if qty < 0:
                errors.append(f"{symbol}: position_qty < 0")
            if sellable < 0 or sellable > qty:
                errors.append(f"{symbol}: sellable_qty 非法")
            if locked < 0:
                errors.append(f"{symbol}: locked_t1_qty < 0")
            if sellable + locked != qty:
                errors.append(f"{symbol}: sellable_qty + locked_t1_qty != position_qty")
            if lot_sum != locked:
                errors.append(f"{symbol}: T+1 批次数量与 locked_t1_qty 不一致")
            if any(lot["buy_date"] != state["current_trading_date"] for lot in position["t1_lots"]):
                errors.append(f"{symbol}: 存在不属于当前交易日的未解锁批次")
            if qty == 0 and dec(position["cost_basis"]) != ZERO:
                errors.append(f"{symbol}: 零持仓但 cost_basis 非零")
            if qty > 0 and dec(position["average_cost"]) != calc(dec(position["cost_basis"]) / Decimal(qty)):
                errors.append(f"{symbol}: average_cost 与 cost_basis / position_qty 不一致")
        if errors:
            raise IntegrityError("INVARIANT_VIOLATION", "; ".join(errors))

    def _blank_state(self, payload: Dict[str, Any], timestamp: str) -> Dict[str, Any]:
        cash = payload["initial_cash"]
        return {
            "schema_version": 1,
            "account_id": payload["account_id"],
            "initial_cash": cash,
            "current_trading_date": payload["trading_date"],
            "day_closed": False,
            "cash": cash,
            "market_value": "0.00",
            "total_equity": cash,
            "realized_pnl": "0.00000000",
            "unrealized_pnl": "0.00000000",
            "total_pnl": "0.00000000",
            "peak_equity": cash,
            "drawdown": "0.00000000",
            "max_drawdown": "0.00000000",
            "positions": {},
            "last_event_seq": 1,
            "last_event_hash": "",
            "updated_at": timestamp,
        }

    def _replay(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not events or events[0]["event_type"] != "ACCOUNT_INITIALIZED":
            raise IntegrityError("MISSING_INIT_EVENT", "账本缺少首个 ACCOUNT_INITIALIZED 事件")
        state = self._blank_state(events[0]["payload"], events[0]["timestamp"])
        state["last_event_hash"] = events[0]["event_hash"]
        for event in events[1:]:
            kind = event["event_type"]
            payload = event["payload"]
            if kind == self.ORDER_EVENT:
                trade = payload.get("trade")
                if trade is not None:
                    self._apply_trade(state, trade, validate_after=True)
            elif kind == "MARK_PRICE":
                symbol = payload["symbol"]
                position = state["positions"].setdefault(symbol, self._empty_position(symbol, payload["market"]))
                position["last_price"] = payload["price"]
                self._recalculate(state, update_peak=True)
            elif kind == "TRADING_DAY_STARTED":
                new_date = payload["trading_date"]
                expected: Dict[str, int] = {}
                for symbol, position in state["positions"].items():
                    remaining = []
                    unlocked = 0
                    for lot in position["t1_lots"]:
                        if lot["buy_date"] < new_date:
                            unlocked += int(lot["qty"])
                        else:
                            remaining.append(lot)
                    if unlocked:
                        expected[symbol] = unlocked
                        position["sellable_qty"] = int(position["sellable_qty"]) + unlocked
                        position["locked_t1_qty"] = int(position["locked_t1_qty"]) - unlocked
                        position["t1_lots"] = remaining
                if expected != payload["unlocked_by_symbol"]:
                    raise IntegrityError("T1_UNLOCK_MISMATCH", f"事件 {event['event_id']} 的解锁数量与账本批次不一致")
                state["current_trading_date"] = new_date
                state["day_closed"] = False
            elif kind == "DAY_ENDED":
                snapshot = payload["snapshot"]
                for field in ["cash", "market_value", "total_equity", "realized_pnl", "unrealized_pnl", "drawdown", "max_drawdown"]:
                    if snapshot[field] != state[field]:
                        raise IntegrityError("DAILY_SNAPSHOT_MISMATCH", f"事件 {event['event_id']} 的 {field} 与账户不一致")
                state["day_closed"] = True
            else:
                raise IntegrityError("UNKNOWN_EVENT_TYPE", f"未知账本事件: {kind}")
            state["last_event_seq"] = event["seq"]
            state["last_event_hash"] = event["event_hash"]
            state["updated_at"] = event["timestamp"]
            self._check_invariants(state)
        return state

    def _append_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        timestamp: str,
        existing_events: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        previous_hash = existing_events[-1]["event_hash"] if existing_events else ZERO_HASH
        event = {
            "seq": len(existing_events) + 1,
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "timestamp": timestamp,
            "previous_hash": previous_hash,
            "payload": payload,
        }
        event["event_hash"] = object_hash(event)
        self._append_jsonl(self.event_path, event)
        return event

    def _read_events(self) -> List[Dict[str, Any]]:
        if not self.event_path.exists():
            raise EngineError("NOT_INITIALIZED", f"账户尚未初始化: {self.data_dir}")
        events: List[Dict[str, Any]] = []
        previous = ZERO_HASH
        with self.event_path.open("r", encoding="utf-8") as handle:
            for line_no, raw in enumerate(handle, 1):
                if not raw.strip():
                    raise IntegrityError("LEDGER_BLANK_LINE", f"账本第 {line_no} 行为空")
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise IntegrityError("LEDGER_JSON_INVALID", f"账本第 {line_no} 行损坏: {exc}") from exc
                event_hash = event.get("event_hash")
                without_hash = {k: v for k, v in event.items() if k != "event_hash"}
                if object_hash(without_hash) != event_hash:
                    raise IntegrityError("LEDGER_HASH_MISMATCH", f"账本第 {line_no} 行哈希校验失败")
                if event.get("previous_hash") != previous:
                    raise IntegrityError("LEDGER_CHAIN_BROKEN", f"账本第 {line_no} 行哈希链断裂")
                if event.get("seq") != line_no:
                    raise IntegrityError("LEDGER_SEQUENCE_ERROR", f"账本第 {line_no} 行序号错误")
                previous = event_hash
                events.append(event)
        return events

    def _load_authoritative(self, *, recover_cache: bool) -> Tuple[List[Dict[str, Any]], Dict[str, Any], bool]:
        events = self._read_events()
        state = self._replay(events)
        recovered = False
        try:
            cached = json.loads(self.account_path.read_text(encoding="utf-8"))
            if cached != state:
                recovered = True
        except (FileNotFoundError, json.JSONDecodeError):
            recovered = True
        if recover_cache:
            self._ensure_projection_files()
            self._sync_all_projections(events)
        if recovered and recover_cache:
            self._write_account(state)
        return events, state, recovered

    def _write_account(self, state: Dict[str, Any]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="account.", suffix=".tmp", dir=self.data_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.account_path)
            try:
                directory_fd = os.open(self.data_dir, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _append_jsonl(self, path: Path, value: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(value) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _assert_monotonic_timestamp(self, events: List[Dict[str, Any]], timestamp: str) -> None:
        if events and datetime.fromisoformat(timestamp) < datetime.fromisoformat(events[-1]["timestamp"]):
            raise EngineError("TIMESTAMP_OUT_OF_ORDER", "时间戳早于账本最后事件，拒绝乱序记账")

    def _assert_current_open_day(self, state: Dict[str, Any], events: List[Dict[str, Any]], timestamp: str) -> None:
        if self._timestamp_date(timestamp) != state["current_trading_date"]:
            raise EngineError("DATE_TIMESTAMP_MISMATCH", f"时间戳不属于当前交易日 {state['current_trading_date']}")
        self._assert_monotonic_timestamp(events, timestamp)
        if state["day_closed"]:
            raise EngineError("DAY_CLOSED", "当前交易日已经 end-day")

    def _find_order(self, events: Iterable[Dict[str, Any]], order_id: str) -> Optional[Dict[str, Any]]:
        for event in events:
            if event["event_type"] == self.ORDER_EVENT and event["payload"]["order"]["order_id"] == order_id:
                record = copy.deepcopy(event["payload"]["order"])
                record["event_id"] = event["event_id"]
                return record
        return None

    def _last_daily_snapshot(self, events: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        last = None
        for event in events:
            if event["event_type"] == "DAY_ENDED":
                last = event["payload"]["snapshot"]
        return last

    def _sync_all_projections(self, events: Iterable[Dict[str, Any]]) -> None:
        for event in events:
            self._sync_projection_event(event)

    def _ensure_projection_files(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for name in (self.ORDER_FILE, self.TRADE_FILE, self.DECISION_FILE):
            path = self.data_dir / name
            if not path.exists():
                with path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.flush()
                    os.fsync(handle.fileno())
        daily = self.data_dir / self.DAILY_FILE
        if not daily.exists() or daily.stat().st_size == 0:
            with daily.open("w", encoding="utf-8-sig", newline="") as handle:
                csv.DictWriter(handle, fieldnames=self.DAILY_FIELDS).writeheader()
                handle.flush()
                os.fsync(handle.fileno())

    def _jsonl_event_ids(self, path: Path) -> set[str]:
        if not path.exists():
            return set()
        result: set[str] = set()
        with path.open("r", encoding="utf-8") as handle:
            for line_no, raw in enumerate(handle, 1):
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise IntegrityError("PROJECTION_JSON_INVALID", f"{path.name} 第 {line_no} 行损坏") from exc
                event_id = item.get("event_id")
                if not event_id or event_id in result:
                    raise IntegrityError("PROJECTION_DUPLICATE", f"{path.name} 存在缺失或重复 event_id")
                result.add(event_id)
        return result

    def _daily_event_ids(self) -> set[str]:
        path = self.data_dir / self.DAILY_FILE
        if not path.exists() or path.stat().st_size == 0:
            return set()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        result = {row["event_id"] for row in rows}
        if len(result) != len(rows):
            raise IntegrityError("PROJECTION_DUPLICATE", f"{self.DAILY_FILE} 存在重复 event_id")
        return result

    def _read_jsonl_records(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        records: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_no, raw in enumerate(handle, 1):
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise IntegrityError("PROJECTION_JSON_INVALID", f"{path.name} 第 {line_no} 行损坏") from exc
                if not isinstance(item, dict):
                    raise IntegrityError("PROJECTION_JSON_INVALID", f"{path.name} 第 {line_no} 行不是 JSON 对象")
                records.append(item)
        return records

    def _expected_projection_records(
        self, events: Iterable[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        orders: List[Dict[str, Any]] = []
        trades: List[Dict[str, Any]] = []
        decisions: List[Dict[str, Any]] = []
        daily: List[Dict[str, Any]] = []
        for event in events:
            if event["event_type"] == self.ORDER_EVENT:
                for target, key in ((orders, "order"), (decisions, "decision")):
                    record = copy.deepcopy(event["payload"][key])
                    record.update({"event_id": event["event_id"], "ledger_seq": event["seq"]})
                    target.append(record)
                if event["payload"].get("trade") is not None:
                    record = copy.deepcopy(event["payload"]["trade"])
                    record.update({"event_id": event["event_id"], "ledger_seq": event["seq"]})
                    trades.append(record)
            elif event["event_type"] == "DAY_ENDED":
                snapshot = event["payload"]["snapshot"]
                daily.append({
                    "event_id": event["event_id"], "date": snapshot["date"],
                    "timestamp": snapshot["timestamp"], "cash": snapshot["cash"],
                    "market_value": snapshot["market_value"], "total_equity": snapshot["total_equity"],
                    "positions_json": canonical_json(snapshot["positions"]),
                    "daily_realized_pnl": snapshot["daily_realized_pnl"],
                    "realized_pnl": snapshot["realized_pnl"], "unrealized_pnl": snapshot["unrealized_pnl"],
                    "daily_return": snapshot["daily_return"], "cumulative_return": snapshot["cumulative_return"],
                    "drawdown": snapshot["drawdown"], "max_drawdown": snapshot["max_drawdown"],
                })
        return orders, trades, decisions, daily

    def _rebuild_projections(self, events: List[Dict[str, Any]]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        orders, trades, decisions, daily = self._expected_projection_records(events)
        for filename, records in (
            (self.ORDER_FILE, orders), (self.TRADE_FILE, trades), (self.DECISION_FILE, decisions)
        ):
            target = self.data_dir / filename
            fd, temp_name = tempfile.mkstemp(prefix=f"{filename}.", suffix=".tmp", dir=self.data_dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    for record in records:
                        handle.write(canonical_json(record) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, target)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
        target = self.data_dir / self.DAILY_FILE
        fd, temp_name = tempfile.mkstemp(prefix=f"{self.DAILY_FILE}.", suffix=".tmp", dir=self.data_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=self.DAILY_FIELDS)
                writer.writeheader()
                writer.writerows(daily)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _sync_projection_event(self, event: Dict[str, Any]) -> None:
        kind = event["event_type"]
        event_id = event["event_id"]
        if kind == self.ORDER_EVENT:
            order_path = self.data_dir / self.ORDER_FILE
            if event_id not in self._jsonl_event_ids(order_path):
                record = copy.deepcopy(event["payload"]["order"])
                record["event_id"] = event_id
                record["ledger_seq"] = event["seq"]
                self._append_jsonl(order_path, record)
            decision_path = self.data_dir / self.DECISION_FILE
            if event_id not in self._jsonl_event_ids(decision_path):
                record = copy.deepcopy(event["payload"]["decision"])
                record["event_id"] = event_id
                record["ledger_seq"] = event["seq"]
                self._append_jsonl(decision_path, record)
            if event["payload"].get("trade") is not None:
                trade_path = self.data_dir / self.TRADE_FILE
                if event_id not in self._jsonl_event_ids(trade_path):
                    record = copy.deepcopy(event["payload"]["trade"])
                    record["event_id"] = event_id
                    record["ledger_seq"] = event["seq"]
                    self._append_jsonl(trade_path, record)
        elif kind == "DAY_ENDED":
            if event_id not in self._daily_event_ids():
                snapshot = event["payload"]["snapshot"]
                row = {
                    "event_id": event_id,
                    "date": snapshot["date"],
                    "timestamp": snapshot["timestamp"],
                    "cash": snapshot["cash"],
                    "market_value": snapshot["market_value"],
                    "total_equity": snapshot["total_equity"],
                    "positions_json": canonical_json(snapshot["positions"]),
                    "daily_realized_pnl": snapshot["daily_realized_pnl"],
                    "realized_pnl": snapshot["realized_pnl"],
                    "unrealized_pnl": snapshot["unrealized_pnl"],
                    "daily_return": snapshot["daily_return"],
                    "cumulative_return": snapshot["cumulative_return"],
                    "drawdown": snapshot["drawdown"],
                    "max_drawdown": snapshot["max_drawdown"],
                }
                self._append_daily_row(row)

    def _append_daily_row(self, row: Dict[str, Any]) -> None:
        path = self.data_dir / self.DAILY_FILE
        write_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.DAILY_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerow(row)
            handle.flush()
            os.fsync(handle.fileno())

    def _projection_report(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        expected_orders, expected_trades, expected_decisions, expected_daily = self._expected_projection_records(events)
        actual_orders = self._read_jsonl_records(self.data_dir / self.ORDER_FILE)
        actual_trades = self._read_jsonl_records(self.data_dir / self.TRADE_FILE)
        actual_decisions = self._read_jsonl_records(self.data_dir / self.DECISION_FILE)
        daily_path = self.data_dir / self.DAILY_FILE
        if daily_path.exists() and daily_path.stat().st_size:
            with daily_path.open("r", encoding="utf-8-sig", newline="") as handle:
                actual_daily = list(csv.DictReader(handle))
        else:
            actual_daily = []
        details = {
            "orders": {"expected": len(expected_orders), "actual": len(actual_orders), "matched": actual_orders == expected_orders},
            "trades": {"expected": len(expected_trades), "actual": len(actual_trades), "matched": actual_trades == expected_trades},
            "decisions": {"expected": len(expected_decisions), "actual": len(actual_decisions), "matched": actual_decisions == expected_decisions},
            "daily_equity": {"expected": len(expected_daily), "actual": len(actual_daily), "matched": actual_daily == expected_daily},
        }
        return {"complete": all(item["matched"] for item in details.values()), **details}


__all__ = ["AccountEngine", "EngineError", "OrderReject", "IntegrityError", "parse_target_weight"]
