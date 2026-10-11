# A股 / BSE 影子账户 Account Engine v1

这是一个只负责纸面账户记账的独立 Python CLI。它不采集行情、不选股、不分析技术形态，也不主动给出买卖建议。所有交易必须来自外部明确指令。

仅使用 Python 3.11+ 标准库，不需要数据库、Web 服务、Docker 或第三方包。

## 1. 先修正的账户逻辑

1. **T+1 必须保存买入批次**：只有 `locked_t1_qty` 汇总无法安全处理连续多个交易日的买入。本程序在每个持仓内保存 `t1_lots`，`new-day` 只在配置认可的交易日解锁早于新交易日的批次。
2. **目标仓位以总权益为基数**：`target_weight=25%` 使用订单参考价重估该股票后的交易前总权益，不是现金的 25%。目标股数按参考价计算，成交现金按含滑点的成交价计算；买入数量向下取合法单位，卖出目标仓位时向保守方向取整，避免仅因取整把剩余仓位压到目标以下。
3. **买入费用进入持仓成本**：加权成本使用 `旧成本总额 + 买入成交额 + 买入费用`。成本总额保留 8 位小数，避免多次部分卖出造成分摊漂移。
4. **卖出不重算剩余股成本**：卖出按原加权平均成本分摊已售成本；剩余股票平均成本保持不变。卖出净收入减去已售成本进入已实现盈亏。
5. **交易费用按成交逐笔计算**：佣金最低收费、印花税、过户费、滑点均来自 `config.json`。示例费率仅是可运行默认值，开始实验前应按你的券商和实验口径确认。
6. **成交价与参考价分离**：传 `reference_price` 时按配置滑点生成 `fill_price`；直接传 `fill_price` 时不再套滑点。成交后参考价作为估值价，因此滑点和买入费用会立即体现在未实现盈亏中。
7. **回撤是负数口径**：`drawdown = total_equity / peak_equity - 1`；`max_drawdown` 保存历史上最小（最负）的回撤值。
8. **多股票独立成本与盈亏**：每个 symbol 独立保存数量、可卖、锁定、成本和盈亏；账户层再汇总现金、市值、权益和回撤。
9. **拒绝优先**：默认卖出请求超过 `sellable_qty` 时整单拒绝。只有显式把 `sell_shortfall` 改成 `execute_available` 才允许执行可卖部分。
10. **账本原子事实**：单个订单的请求、结果、成交和决策被放进同一个哈希链事件后才写 `account.json`，避免多文件之间没有事务造成“订单有了但成交丢了”。

## 2. 项目与运行数据结构

```text
account_engine/
├── account.py                 # CLI
├── engine.py                  # 核心规则、重放、校验
├── reporting.py               # 离线 HTML 报告生成器
├── config.json                # 资金、费用、市场单位、日历、拒绝策略
├── README.md
├── tests/
│   └── test_account_engine.py
└── data/                      # init 后生成，可用 --data-dir 改位置
    ├── account_events.jsonl   # 唯一事实源；逐事件 SHA-256 哈希链
    ├── account.json           # 当前状态缓存，可完全重建
    ├── orders.jsonl           # 订单审计投影，含拒绝和 HOLD
    ├── trades.jsonl           # 实际纸面成交投影
    ├── decision_log.jsonl     # 决策理由与证伪条件投影
    ├── daily_equity.csv       # 日终快照投影（UTF-8 BOM，Excel 可直接开）
    ├── account_report.html    # 初始化及每次账户变更后自动生成的只读可视化报告
    └── .account_engine.lock   # 进程互斥锁
```

`account_events.jsonl` 是唯一事实源。其他文件都是只追加投影；`account.json` 损坏或缺失时可重建。日志使用哈希链实现“可检测篡改”，但本地文件系统本身不是 WORM 存储；如需更强不可变性，应定期把日志复制到只读介质或做外部哈希存证。

核心状态中，账户级保存 `cash / market_value / total_equity / realized_pnl / unrealized_pnl / total_pnl / peak_equity / drawdown / max_drawdown`；每个 symbol 保存 `position_qty / sellable_qty / locked_t1_qty / t1_lots / cost_basis / average_cost / last_price / market_value / realized_pnl / unrealized_pnl / total_pnl`。

所有金额、价格、比例在 JSON 中保存为十进制字符串，核心计算使用 `Decimal`，不使用二进制浮点数。

## 3. 命令接口

所有命令输出 JSON。成功退出码为 0；输入/规则错误为 2；`verify` 或 `rebuild --check-only` 发现不一致为 3。

全局参数必须放在子命令前：

```bash
python account.py --data-dir ./data --config ./config.json COMMAND ...
```

### 初始化与查询

```bash
python account.py init --date 2026-09-01 --timestamp 2026-09-01T09:00:00+08:00
python account.py status
python account.py verify
python account.py rebuild
python account.py rebuild --check-only
python account.py report
```

### BUY / ADD / REDUCE

`--qty` 与 `--target-weight` 必须二选一；`--reference-price` 与 `--fill-price` 必须二选一。

```bash
python account.py buy \
  --order-id O0001 --decision-id D0001 --symbol 000045 \
  --target-weight 25% --reference-price 10.82 \
  --timestamp 2026-09-01T10:00:00+08:00 \
  --reason "缩量回踩后重新夺回关键位" \
  --invalidation "放量跌破10.70且不能快速收回"

python account.py add \
  --order-id O0002 --decision-id D0002 --symbol 000045 \
  --qty 2000 --fill-price 11.05 \
  --timestamp 2026-09-02T10:00:00+08:00 \
  --reason "外部决策明确要求加仓" --invalidation "失守10.80"

python account.py reduce \
  --order-id O0003 --decision-id D0003 --symbol 000045 \
  --target-weight 15% --reference-price 11.30 \
  --timestamp 2026-09-02T13:30:00+08:00 \
  --reason "外部决策明确要求降至15%" --invalidation "重新转强再评估"
```

### EXIT / HOLD

```bash
python account.py exit \
  --order-id O0004 --decision-id D0004 --symbol 000045 \
  --reference-price 10.60 --timestamp 2026-09-03T10:00:00+08:00 \
  --reason "外部决策要求离场" --invalidation "无"

python account.py hold \
  --order-id O0005 --decision-id D0005 --symbol 000045 \
  --timestamp 2026-09-03T11:00:00+08:00 \
  --reason "外部决策为继续观察" --invalidation "跌破指定价位"
```

### 估值、T+1 与日终

```bash
python account.py mark --symbol 000045 --price 11.20 --timestamp 2026-09-01T14:50:00+08:00
python account.py end-day --timestamp 2026-09-01T15:05:00+08:00
python account.py new-day --date 2026-09-02 --timestamp 2026-09-02T09:00:00+08:00
```

`new-day` 不是自然日零点任务。它验证 `config.json` 的交易日历，并且默认要求上一交易日已经 `end-day`。节假日必须维护在 `trading_calendar.holidays`；周末调休交易日可放入 `extra_trading_days`。

日终权益以各持仓最后一次 `MARK_PRICE`（或最近一次交易所携带的参考/成交价）估值。多股票账户收盘前应逐只更新收盘价；未更新的股票会继续沿用旧价，程序不会猜测行情。

### 离线可视化报告

```bash
python account.py report
```

默认生成 `data/account_report.html`。初始化、交易、估值、日终及进入新交易日后都会自动重建报告；已经在浏览器中打开的页面每 2 秒自动刷新，因此不需要手动再次运行 `report`。页面不依赖网络、CDN或第三方 JavaScript。内容包括账户总览、当前持仓、T+1 可卖/锁定比例、日终权益与回撤曲线、订单、成交和决策日志。

也可以指定输出位置：

```bash
python account.py report --output ./account_report.html
```

生成报告只读取并重放 `account_events.jsonl`，不会修改账户状态或任何账本事实。

## 4. 执行语义

- `BUY`：严格模式下仅允许空仓首次建立。
- `ADD`：严格模式下要求已有持仓。
- `REDUCE`：按明确股数或“成交后目标仓位”减少持仓。
- `EXIT`：请求卖出全部持仓；若部分股票仍受 T+1 锁定，默认整单拒绝。
- `HOLD`：只记录决策，不改变账户。
- `MARK_PRICE`：只更新 `last_price`、市值、未实现盈亏、权益、峰值和回撤。

目标仓位的总权益基数会先用订单的参考/成交价格重估目标股票，但不会把这个临时重估单独写成 `MARK_PRICE`。目标仓位买入因现金不足时默认自动缩小到最大合法可买数量，并标记 `PARTIALLY_FILLED`；明确股数买入资金不足则整单拒绝。

同一个 `order_id` 再次提交相同业务参数时直接返回原结果并标记 `duplicate=true`，不会再次记账。相同 `order_id` 但业务参数不同会报 `DUPLICATE_ORDER_CONFLICT`。拒绝订单也会永久占用其 `order_id`。

## 5. 费用和市场单位

费率全部位于 `config.json`。程序按每笔成交分别计算：

```text
买入现金变化 = -(成交金额 + 佣金 + 过户费)
卖出现金变化 =  成交金额 - 佣金 - 印花税 - 过户费
```

市场规则分离了 `min_buy_qty / buy_step_qty / min_sell_qty / sell_step_qty / allow_sell_all_odd_lot`。默认配置包含沪市主板、深市、创业板、科创板和北交所，并通过可配置正则映射代码。若券商或规则口径不同，请只改配置，不改核心逻辑。

## 6. 运行测试

```bash
cd account_engine
python -m unittest discover -s tests -v
```

测试覆盖 32 个场景：首次目标仓位买入、同日及跨日多批次 T+1、同日清仓拒绝、次交易日解锁、部分减仓和全部清仓、平均成本与精确费用/盈亏、资金不足、重复订单幂等与冲突、MARK_PRICE 不改持仓、回撤历史极值、账户精确重建、多股票汇总、北交所交易步长、非交易日不解锁、目标仓位以权益为基数、滑点方向与直接成交价、日终快照、完整性校验、初始化文件完整性、缺失或内容被改写的投影检测与修复、交易后自动更新 HTML 报告，以及空账户/有交易账户的 HTML 报告和决策文本转义。

## 7. 完整演示：20 万元空仓到离场

以下日期仅为命令演示；运行前请把实际休市日补进配置。

```bash
python account.py --data-dir ./demo init --date 2026-09-01 --timestamp 2026-09-01T09:00:00+08:00

# 第一天：25% 试错仓。10.82 元时目标市值约 50,000 元，深市单位取整为 4,600 股。
python account.py --data-dir ./demo buy --order-id O0001 --decision-id D0001 --symbol 000045 --target-weight 25% --reference-price 10.82 --timestamp 2026-09-01T10:00:00+08:00 --reason "建立25%试错仓" --invalidation "放量跌破10.70且不能快速收回"
python account.py --data-dir ./demo mark --symbol 000045 --price 10.95 --timestamp 2026-09-01T14:50:00+08:00
python account.py --data-dir ./demo end-day --timestamp 2026-09-01T15:05:00+08:00

# 第二天开始：4,600 股由锁定转为可卖；随后加仓 2,000 股，新买部分继续锁定。
python account.py --data-dir ./demo new-day --date 2026-09-02 --timestamp 2026-09-02T09:00:00+08:00
python account.py --data-dir ./demo add --order-id O0002 --decision-id D0002 --symbol 000045 --qty 2000 --reference-price 11.05 --timestamp 2026-09-02T10:00:00+08:00 --reason "外部决策要求加仓" --invalidation "跌破10.80"

# 此时 position=6,600、sellable=4,600、locked=2,000。减仓 2,000 股合法。
python account.py --data-dir ./demo reduce --order-id O0003 --decision-id D0003 --symbol 000045 --qty 2000 --reference-price 11.30 --timestamp 2026-09-02T13:30:00+08:00 --reason "外部决策要求降低风险" --invalidation "重新站回11.40"
python account.py --data-dir ./demo end-day --timestamp 2026-09-02T15:05:00+08:00

# 第三天：第二天新买的 2,000 股解锁，剩余 4,600 股均可卖，执行 EXIT。
python account.py --data-dir ./demo new-day --date 2026-09-03 --timestamp 2026-09-03T09:00:00+08:00
python account.py --data-dir ./demo exit --order-id O0004 --decision-id D0004 --symbol 000045 --reference-price 10.60 --timestamp 2026-09-03T10:00:00+08:00 --reason "证伪条件触发，外部决策要求离场" --invalidation "无"
python account.py --data-dir ./demo mark --symbol 000045 --price 10.60 --timestamp 2026-09-03T14:50:00+08:00
python account.py --data-dir ./demo end-day --timestamp 2026-09-03T15:05:00+08:00
python account.py --data-dir ./demo verify
python account.py --data-dir ./demo status
python account.py --data-dir ./demo report
```

演示中，第二天加仓后立即执行 `EXIT` 会因 2,000 股仍锁定而整单拒绝；这正是默认的“不擅自改变交易意图”策略。

## 8. v1 明确边界

v1 不处理分红、送股、配股、拆并股、除权成本调整、资金申购赎回或人工入金/出金，也不判断停牌、涨跌停和成交可得性。若一个月实验中发生这些事项，不要手工编辑日志或 `account.json`；应先为对应事实增加新的账本事件类型。外部系统只有在确认纸面成交成立后，才应向本引擎提交交易指令及价格。
