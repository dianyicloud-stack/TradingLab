"""Generate a self-contained, read-only HTML account report."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any, Dict, Iterable, List, Sequence


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _h(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def _money(value: Any, *, signed: bool = False) -> str:
    number = _d(value)
    prefix = "+" if signed and number > 0 else ""
    return f"{prefix}¥{number:,.2f}"


def _price(value: Any) -> str:
    return f"{_d(value):,.4f}".rstrip("0").rstrip(".")


def _pct(value: Any, *, signed: bool = True) -> str:
    number = _d(value) * Decimal("100")
    prefix = "+" if signed and number > 0 else ""
    return f"{prefix}{number:.2f}%"


def _number_class(value: Any) -> str:
    number = _d(value)
    if number > 0:
        return "positive"
    if number < 0:
        return "negative"
    return "neutral"


def _status_class(status: Any) -> str:
    return {
        "FILLED": "ok",
        "PARTIALLY_FILLED": "warn",
        "HELD": "info",
        "REJECTED": "bad",
    }.get(str(status), "plain")


def _empty_row(columns: int, message: str) -> str:
    return f'<tr><td colspan="{columns}" class="empty-cell">{_h(message)}</td></tr>'


def _chart_svg(values: Sequence[Decimal], labels: Sequence[str], *, kind: str) -> str:
    if not values:
        return '<div class="empty-panel">还没有日终快照。执行 end-day 后将显示曲线。</div>'
    width, height = 1000.0, 260.0
    left, right, top, bottom = 74.0, 24.0, 20.0, 42.0
    chart_w, chart_h = width - left - right, height - top - bottom
    low, high = min(values), max(values)
    if kind == "drawdown":
        high = max(high, Decimal("0"))
    if low == high:
        pad = abs(low) * Decimal("0.01") or Decimal("1")
        low -= pad
        high += pad
    span = high - low

    def x_at(index: int) -> float:
        if len(values) == 1:
            return left + chart_w / 2
        return left + chart_w * index / (len(values) - 1)

    def y_at(value: Decimal) -> float:
        return top + chart_h * float((high - value) / span)

    points = " ".join(f"{x_at(i):.2f},{y_at(value):.2f}" for i, value in enumerate(values))
    baseline = top + chart_h
    area_points = f"{left:.2f},{baseline:.2f} {points} {x_at(len(values) - 1):.2f},{baseline:.2f}"
    grid: List[str] = []
    for index in range(5):
        ratio = Decimal(index) / Decimal("4")
        y = top + chart_h * index / 4
        value = high - span * ratio
        label = _money(value) if kind == "equity" else _pct(value, signed=False)
        grid.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" class="grid" />'
            f'<text x="{left-10}" y="{y+4:.2f}" text-anchor="end" class="axis-label">{_h(label)}</text>'
        )
    dots = "".join(
        f'<circle cx="{x_at(i):.2f}" cy="{y_at(value):.2f}" r="3.5"><title>{_h(labels[i])}: {_h(_money(value) if kind == "equity" else _pct(value))}</title></circle>'
        for i, value in enumerate(values)
    )
    first_label = labels[0]
    last_label = labels[-1]
    color_class = "equity-line" if kind == "equity" else "drawdown-line"
    return (
        f'<svg viewBox="0 0 {int(width)} {int(height)}" class="chart" role="img">'
        f'<title>{"总权益曲线" if kind == "equity" else "回撤曲线"}</title>'
        + "".join(grid)
        + f'<polygon points="{area_points}" class="{color_class} area" />'
        + f'<polyline points="{points}" class="{color_class} line" />'
        + f'<g class="{color_class} dots">{dots}</g>'
        + f'<text x="{left}" y="{height-12}" class="axis-label">{_h(first_label)}</text>'
        + f'<text x="{width-right}" y="{height-12}" text-anchor="end" class="axis-label">{_h(last_label)}</text>'
        + "</svg>"
    )


def render_account_report(state: Dict[str, Any], events: Iterable[Dict[str, Any]], generated_at: str) -> str:
    event_list = list(events)
    orders = [event["payload"]["order"] for event in event_list if event["event_type"] == "ORDER_PROCESSED"]
    trades = [event["payload"]["trade"] for event in event_list if event["event_type"] == "ORDER_PROCESSED" and event["payload"].get("trade")]
    decisions = [event["payload"]["decision"] for event in event_list if event["event_type"] == "ORDER_PROCESSED"]
    snapshots = [event["payload"]["snapshot"] for event in event_list if event["event_type"] == "DAY_ENDED"]
    active_positions = [position for position in state["positions"].values() if int(position["position_qty"]) > 0]

    cards = [
        ("总权益", _money(state["total_equity"]), "neutral", f"初始 {_money(state['initial_cash'])}"),
        ("现金", _money(state["cash"]), "neutral", f"占权益 {_pct(_d(state['cash']) / _d(state['total_equity']), signed=False) if _d(state['total_equity']) else '—'}"),
        ("持仓市值", _money(state["market_value"]), "neutral", f"{len(active_positions)} 只在持"),
        ("累计盈亏", _money(state["total_pnl"], signed=True), _number_class(state["total_pnl"]), f"累计收益 {_pct(_d(state['total_equity']) / _d(state['initial_cash']) - 1) if _d(state['initial_cash']) else '—'}"),
        ("已实现盈亏", _money(state["realized_pnl"], signed=True), _number_class(state["realized_pnl"]), "已完成卖出的损益"),
        ("未实现盈亏", _money(state["unrealized_pnl"], signed=True), _number_class(state["unrealized_pnl"]), "当前持仓浮动损益"),
        ("当前回撤", _pct(state["drawdown"]), _number_class(state["drawdown"]), f"峰值 {_money(state['peak_equity'])}"),
        ("最大回撤", _pct(state["max_drawdown"]), _number_class(state["max_drawdown"]), "负数口径"),
    ]
    cards_html = "".join(
        f'<article class="metric-card"><div class="metric-label">{_h(label)}</div><div class="metric-value {css}">{_h(value)}</div><div class="metric-note">{_h(note)}</div></article>'
        for label, value, css, note in cards
    )

    position_rows: List[str] = []
    for position in sorted(active_positions, key=lambda item: item["symbol"]):
        qty = int(position["position_qty"])
        sellable = int(position["sellable_qty"])
        locked = int(position["locked_t1_qty"])
        sellable_width = 100 * sellable / qty if qty else 0
        locked_width = 100 - sellable_width if qty else 0
        position_rows.append(
            "<tr>"
            f'<td><strong>{_h(position["symbol"])}</strong><span class="subline">{_h(position["market"])}</span></td>'
            f'<td class="num">{qty:,}</td><td class="num">{sellable:,}</td><td class="num">{locked:,}</td>'
            f'<td class="num">{_h(_price(position["average_cost"]))}</td><td class="num">{_h(_price(position["last_price"]))}</td>'
            f'<td class="num">{_h(_money(position["market_value"]))}</td>'
            f'<td class="num {_number_class(position["unrealized_pnl"])}">{_h(_money(position["unrealized_pnl"], signed=True))}</td>'
            f'<td class="num {_number_class(position["realized_pnl"])}">{_h(_money(position["realized_pnl"], signed=True))}</td>'
            f'<td><div class="t1-bar"><span class="sellable" style="width:{sellable_width:.2f}%"></span><span class="locked" style="width:{locked_width:.2f}%"></span></div><span class="subline">可卖 {sellable_width:.1f}% · 锁定 {locked_width:.1f}%</span></td>'
            "</tr>"
        )
    if not position_rows:
        position_rows.append(_empty_row(10, "当前为空仓"))

    daily_rows: List[str] = []
    for item in reversed(snapshots):
        daily_rows.append(
            "<tr>"
            f'<td>{_h(item["date"])}</td><td class="num">{_h(_money(item["cash"]))}</td>'
            f'<td class="num">{_h(_money(item["market_value"]))}</td><td class="num"><strong>{_h(_money(item["total_equity"]))}</strong></td>'
            f'<td class="num {_number_class(item["daily_realized_pnl"])}">{_h(_money(item["daily_realized_pnl"], signed=True))}</td>'
            f'<td class="num {_number_class(item["unrealized_pnl"])}">{_h(_money(item["unrealized_pnl"], signed=True))}</td>'
            f'<td class="num {_number_class(item["daily_return"])}">{_h(_pct(item["daily_return"]))}</td>'
            f'<td class="num {_number_class(item["cumulative_return"])}">{_h(_pct(item["cumulative_return"]))}</td>'
            f'<td class="num negative">{_h(_pct(item["drawdown"]))}</td>'
            "</tr>"
        )
    if not daily_rows:
        daily_rows.append(_empty_row(9, "尚无日终记录"))

    order_rows: List[str] = []
    for order in reversed(orders):
        request_size = f'{order["requested_qty"]:,} 股' if order.get("requested_qty") else (_pct(order["requested_target_weight"], signed=False) if order.get("requested_target_weight") is not None else "—")
        price_text = order.get("fill_price") or order.get("reference_price") or "—"
        reject = order.get("reject_reason") or ""
        reject_html = f'<span class="subline negative">{_h(reject)}</span>' if reject else ""
        invalidation_html = f'<span class="subline">证伪：{_h(order.get("invalidation_condition") or "—")}</span>'
        order_rows.append(
            "<tr>"
            f'<td>{_h(order["timestamp"])}</td><td><strong>{_h(order["order_id"])}</strong><span class="subline">{_h(order["decision_id"])}</span></td>'
            f'<td><strong>{_h(order["symbol"])}</strong><span class="subline">{_h(order["market"])}</span></td><td>{_h(order["action"])}</td>'
            f'<td class="num">{_h(request_size)}</td><td class="num">{int(order.get("executed_qty") or 0):,}</td><td class="num">{_h(price_text)}</td>'
            f'<td><span class="status {_status_class(order["status"])}">{_h(order["status"])}</span>{reject_html}</td>'
            f'<td class="wrap"><strong>{_h(order["reason"])}</strong>{invalidation_html}</td>'
            "</tr>"
        )
    if not order_rows:
        order_rows.append(_empty_row(9, "尚无订单或 HOLD 记录"))

    trade_rows: List[str] = []
    for trade in reversed(trades):
        pnl = trade.get("realized_pnl_delta", "0")
        trade_rows.append(
            "<tr>"
            f'<td>{_h(trade["timestamp"])}</td><td><strong>{_h(trade["trade_id"])}</strong><span class="subline">{_h(trade["order_id"])}</span></td>'
            f'<td>{_h(trade["symbol"])}</td><td><span class="side {str(trade["side"]).lower()}">{_h(trade["side"])}</span></td>'
            f'<td class="num">{int(trade["executed_qty"]):,}</td><td class="num">{_h(_price(trade["fill_price"]))}</td>'
            f'<td class="num">{_h(_money(trade["gross_amount"]))}</td><td class="num">{_h(_money(trade["fees"]["total"]))}</td>'
            f'<td class="num {_number_class(trade["net_cash_change"])}">{_h(_money(trade["net_cash_change"], signed=True))}</td>'
            f'<td class="num {_number_class(pnl)}">{_h(_money(pnl, signed=True))}</td>'
            "</tr>"
        )
    if not trade_rows:
        trade_rows.append(_empty_row(10, "尚无成交记录"))

    decision_rows: List[str] = []
    for item in reversed(decisions):
        decision_rows.append(
            "<tr>"
            f'<td>{_h(item["timestamp"])}</td><td><strong>{_h(item["decision_id"])}</strong><span class="subline">{_h(item["order_id"])}</span></td>'
            f'<td>{_h(item["symbol"])}</td><td>{_h(item["action"])}</td><td class="wrap">{_h(item["reason"])}</td>'
            f'<td class="wrap">{_h(item.get("invalidation_condition") or "—")}</td><td><span class="status {_status_class(item["order_status"])}">{_h(item["order_status"])}</span></td>'
            "</tr>"
        )
    if not decision_rows:
        decision_rows.append(_empty_row(7, "尚无决策记录"))

    equity_chart = _chart_svg([_d(item["total_equity"]) for item in snapshots], [item["date"] for item in snapshots], kind="equity")
    drawdown_chart = _chart_svg([_d(item["drawdown"]) for item in snapshots], [item["date"] for item in snapshots], kind="drawdown")
    day_status = "已收盘" if state["day_closed"] else "交易日进行中"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="2">
<title>A股 / BSE 影子账户报告</title>
<style>
:root{{--bg:#f3f6fb;--panel:#fff;--ink:#162033;--muted:#6e7b91;--line:#e2e8f0;--accent:#3167e3;--positive:#d33b32;--negative:#16946c;--warning:#c27a00;--locked:#ef9f43;--sellable:#4e8cf5;--shadow:0 8px 28px rgba(23,36,64,.07)}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}} .container{{max-width:1480px;margin:auto;padding:28px}}
.hero{{background:linear-gradient(125deg,#182a55,#294b93 62%,#386fda);color:#fff;border-radius:20px;padding:26px 30px;box-shadow:var(--shadow);display:flex;justify-content:space-between;gap:20px;align-items:flex-end}}
.hero h1{{font-size:28px;margin:0 0 8px}} .hero p{{margin:0;color:#dbe6ff}} .hero-meta{{text-align:right;white-space:nowrap}} .hero-meta strong{{display:block;font-size:18px}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:18px 0}} .metric-card,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow)}} .metric-card{{padding:18px 20px}} .metric-label{{color:var(--muted);font-size:13px}} .metric-value{{font-size:24px;font-weight:750;margin:5px 0}} .metric-note,.subline{{display:block;color:var(--muted);font-size:12px;margin-top:3px}}
.panel{{margin:18px 0;overflow:hidden}} .panel-head{{padding:18px 20px 12px;display:flex;justify-content:space-between;align-items:center}} .panel h2{{font-size:18px;margin:0}} .panel-note{{color:var(--muted);font-size:12px}} .panel-body{{padding:0 20px 20px}} .chart-grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}} .chart{{width:100%;height:auto;display:block}} .grid{{stroke:#e9edf4;stroke-width:1}} .axis-label{{fill:#7a879b;font-size:12px}} .line{{fill:none;stroke-width:3}} .area{{opacity:.09}} .equity-line.line{{stroke:#3167e3}} .equity-line.area{{fill:#3167e3}} .equity-line.dots circle{{fill:#3167e3}} .drawdown-line.line{{stroke:#16946c}} .drawdown-line.area{{fill:#16946c}} .drawdown-line.dots circle{{fill:#16946c}}
.table-wrap{{overflow:auto}} table{{width:100%;border-collapse:collapse;min-width:900px}} th{{background:#f7f9fc;color:#66748a;font-size:12px;font-weight:650;text-align:left;position:sticky;top:0}} th,td{{padding:11px 12px;border-top:1px solid var(--line);vertical-align:top}} td.num,th.num{{text-align:right;white-space:nowrap}} td.wrap{{min-width:220px;max-width:380px;white-space:normal}} tbody tr:hover{{background:#fbfcff}} .positive{{color:var(--positive)}} .negative{{color:var(--negative)}} .neutral{{color:var(--ink)}}
.status,.side{{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:750}} .status.ok{{color:#176747;background:#e7f7ef}} .status.warn{{color:#8b5d00;background:#fff4d8}} .status.bad{{color:#a73232;background:#ffeded}} .status.info{{color:#2856a9;background:#eaf1ff}} .status.plain{{background:#edf0f5}} .side.buy{{color:#a73232;background:#ffeded}} .side.sell{{color:#176747;background:#e7f7ef}}
.t1-bar{{height:9px;border-radius:99px;background:#edf1f7;display:flex;overflow:hidden;min-width:120px;margin-top:5px}} .t1-bar .sellable{{background:var(--sellable)}} .t1-bar .locked{{background:var(--locked)}} .empty-cell,.empty-panel{{color:var(--muted);text-align:center;padding:34px}} footer{{color:var(--muted);font-size:12px;padding:6px 2px 24px;word-break:break-all}}
@media(max-width:980px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.chart-grid{{grid-template-columns:1fr}}.hero{{align-items:flex-start;flex-direction:column}}.hero-meta{{text-align:left}}}} @media(max-width:560px){{.container{{padding:12px}}.metrics{{grid-template-columns:1fr 1fr;gap:8px}}.metric-card{{padding:14px}}.metric-value{{font-size:18px}}.hero{{padding:20px;border-radius:14px}}.hero h1{{font-size:22px}}}}
@media print{{body{{background:#fff}}.container{{max-width:none;padding:0}}.hero,.metric-card,.panel{{box-shadow:none}}.panel{{break-inside:avoid}}}}
</style>
</head>
<body><main class="container">
<header class="hero"><div><h1>A股 / BSE 影子账户报告</h1><p>账本驱动 · 只读派生 · 不连接行情</p></div><div class="hero-meta"><strong>{_h(state['current_trading_date'])} · {_h(day_status)}</strong><span>生成时间 {_h(generated_at)}</span></div></header>
<section class="metrics">{cards_html}</section>
<section class="panel"><div class="panel-head"><h2>当前持仓与 T+1</h2><span class="panel-note">蓝色为可卖，橙色为当日锁定</span></div><div class="table-wrap"><table><thead><tr><th>代码/市场</th><th class="num">持仓</th><th class="num">可卖</th><th class="num">T+1锁定</th><th class="num">平均成本</th><th class="num">最新价</th><th class="num">市值</th><th class="num">未实现盈亏</th><th class="num">已实现盈亏</th><th>T+1结构</th></tr></thead><tbody>{''.join(position_rows)}</tbody></table></div></section>
<section class="chart-grid"><article class="panel"><div class="panel-head"><h2>总权益曲线</h2><span class="panel-note">基于日终快照</span></div><div class="panel-body">{equity_chart}</div></article><article class="panel"><div class="panel-head"><h2>回撤曲线</h2><span class="panel-note">负数口径</span></div><div class="panel-body">{drawdown_chart}</div></article></section>
<section class="panel"><div class="panel-head"><h2>日终权益</h2><span class="panel-note">{len(snapshots)} 个快照</span></div><div class="table-wrap"><table><thead><tr><th>日期</th><th class="num">现金</th><th class="num">市值</th><th class="num">总权益</th><th class="num">当日已实现</th><th class="num">未实现</th><th class="num">当日收益</th><th class="num">累计收益</th><th class="num">回撤</th></tr></thead><tbody>{''.join(daily_rows)}</tbody></table></div></section>
<section class="panel"><div class="panel-head"><h2>订单与指令</h2><span class="panel-note">含 HOLD 与拒绝记录 · 共 {len(orders)} 条</span></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>订单/决策</th><th>代码/市场</th><th>动作</th><th class="num">请求</th><th class="num">成交股数</th><th class="num">成交价</th><th>状态</th><th>理由与证伪</th></tr></thead><tbody>{''.join(order_rows)}</tbody></table></div></section>
<section class="panel"><div class="panel-head"><h2>成交记录</h2><span class="panel-note">共 {len(trades)} 笔</span></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>成交/订单</th><th>代码</th><th>方向</th><th class="num">股数</th><th class="num">成交价</th><th class="num">成交额</th><th class="num">费用</th><th class="num">现金变化</th><th class="num">已实现盈亏</th></tr></thead><tbody>{''.join(trade_rows)}</tbody></table></div></section>
<section class="panel"><div class="panel-head"><h2>决策日志</h2><span class="panel-note">理由只展示，不评价</span></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>决策/订单</th><th>代码</th><th>动作</th><th>当时理由</th><th>证伪条件</th><th>结果</th></tr></thead><tbody>{''.join(decision_rows)}</tbody></table></div></section>
<footer>账户ID：{_h(state['account_id'])} · 账本事件：{len(event_list)} · 最后序号：{state['last_event_seq']} · 最后事件哈希：{_h(state['last_event_hash'])}<br>本报告是静态只读快照。权益使用账本中的最后标记价格；生成报告不会修改持仓、成本、盈亏或账本。</footer>
</main></body></html>"""


__all__ = ["render_account_report"]
