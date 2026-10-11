# M2.2.1 Live Productization & Architecture Alignment

## Architecture review

M2.2 的事实库与运行库已经物理分离，但原实现仍有四个产品化缺口：`auto_ai` 只有布尔语义；
Advisory 新旧判断以整块输入 hash 判断，增量证据与历史上下文没有显式边界；同股票请求只有全局进程锁，
没有可观察的协调状态；Live 将长篇 AI 文本放在结论之前。Learning 也没有接收用户主动保存 Advisory 的契约。

M2.2.1 保持 `Frontend -> API -> AdvisoryService -> Repository / Provider Port`。LIVE 拥有 Fast Advisory，
DECISIONS 拥有 Formal Decision/ACK，LEARNING 拥有训练事实，V2A 拥有 Workspace 与 Confirmed Cursor。
V2A/V2B/Account 的 Legacy 文件、枚举和 ACK/Receipt 协议均未修改。

## Data classes and repositories

| Class | Data | Repository |
|---|---|---|
| Immutable business facts | Frozen Advisory Input、AdvisoryOpinion | `data/decisions/advisory/advisory.db`，UPDATE/DELETE trigger 禁止修改 |
| Mutable runtime | Advisory Cursor、debounce pending、per-symbol coordinator、失败诊断 | `data/runtime/live/advisory/advisory_runtime.db` |
| User preferences | Provider、Model、reasoning、Auto AI mode、阈值、重要事件类型、Pin 顺序 | 同一 runtime DB 的独立 settings 表语义 |
| Learning fact | 用户主动保存的 `source_advisory_id` 与 snapshot reference | `learning.db.saved_advisory_cases`，append-only |

没有迁移现有 Opinion，也没有为了重构搬动 SQLite。旧 Opinion 缺少 M2.2.1 字段时继续可读，字段为 nullable。

## Cursors and frozen windows

V2A Confirmed Cursor 只由正式 ACK 链推进。Trading Lab Advisory Cursor 只表示 Fast Advisory 已处理到哪里。
任一 Cursor 的推进都不会写另一个 Cursor，也不会修改历史 Opinion。

每次 Frozen Input 记录：

- `incremental_window_start/end`：相对上一 Advisory Cursor 真正新增的数据范围。
- `context_window_start/end`：为解释增量而读取的有限历史范围。
- `input_event_seq_from/to`：只包含未分析 Event；旧 Event 仅可进入 context。
- `input_observation_time_from/to`：只包含未分析 Observation。
- `generated_at`：Opinion 的实际生成时刻。

新增窗口完整保留；上下文最多保留最近 20 个 Event、12 个 Observation、上一条 Opinion 和更早历史的结构化摘要。
Prompt 固定为 Role、Frozen Window、Previous Advisory、Incremental Evidence、Current Context、Reasoning Tasks、Output Schema 七层，
不会随盘中时间无限增长。

## Delta, game and scenarios

`delta_since_previous` 由 Service 基于相邻 Frozen Input 计算价格、VWAP gap、Alpha、量能、成交额、换手、量比和
price efficiency 的 previous/current/change/direction。AI 解释差值，不重新计算事实。Action 与 dominance score 的迁移在
Opinion 写入前补齐。

`game_state` 支持 buyer/seller/absorption/initiative/supply/demand/price impact 的结构化表达，并兼容已有文本 Opinion。
Scenario 保留 conditions、interpretation、recommended action、confirmation、invalidation；下一观察重点支持
`target/watch_for/meaning` checklist。顶层只展示当前主假设失效条件。

Previous Hypothesis Review 增加 previous advisory ID、生成时间、优势方、优势分数和 Action。Meaningful Change 计算
`INFO / NOTICE / IMPORTANT / CRITICAL`；Action/优势方变化、显著分数变化、假设失效和退出风险逐级提升。

## Queue, auto mode and freshness

每个 `tracking_session_id / symbol` 同时最多一个 active AI request。AI 运行期间的请求只标记 pending aggregation；
当前请求结束后由 Watcher 依据 Advisory Cursor 和 debounce 生成下一 Frozen Input。不同股票互不需要共享业务锁。

Auto AI 模式为：

- `OFF`：不自动分析，Manual 始终可用。
- `IMPORTANT_ONLY`：仅配置的重要类型或 IMPORTANT/CRITICAL 事件触发。
- `ALL_EVENTS`：所有满足增量条件的新 Event 可触发。

debounce 默认 4 秒，只负责短时聚合，不替代 Cursor、Coordinator 或 Frozen Window。

数据新鲜度阈值在 Domain settings 中配置，默认 90 秒内 FRESH、300 秒内 DELAYED、其后 STALE。STALE 时自动 AI 暂停；
手动分析先要求明确确认，确认后的 Opinion 标记 `source_freshness=STALE`。Provider timeout、网络错误或 Schema 失败会追加失败诊断，
保留上一条成功 Opinion，并允许重试。

## Product surfaces and API

Live 第一屏按股票显示数据状态、最新时间、延迟、Watcher、AI 状态，以及 Action、Confidence、窗口、触发方式、实际模型、
实际 reasoning、耗时、优势迁移、Previous Hypothesis、核心矛盾、结构化差值、Scenario、观察 checklist 和主假设失效条件。
Confidence 的 tooltip 明确它是结构判断置信度，不是上涨概率、收益概率或胜率。详细博弈、Evidence、完整价位、历史与正式审计默认折叠。

历史默认提供博弈时间轴。排序先尊重 Pin，再考虑风险升级、Action 变化、新 Opinion、显著优势变化和数据延迟。
Decisions 默认仍是今日 LIVE Formal Decision，每股票最新一条；HO/EHO/Correlation/ACK/Receipt/Worker Generation/Hash 在高级审计。

API：

- `GET/PUT /api/live/advisory/settings`
- `GET /api/live/{symbol}/advisory/latest`
- `GET /api/live/{symbol}/advisory/history`
- `GET /api/live/{symbol}/advisory/timeline`
- `POST /api/live/{symbol}/advisory/analyze`
- `GET /api/live/health`
- `POST /api/learning/cases/from-advisory`

保存训练案例只在用户点击后发生。Learning 写入幂等、append-only 的来源引用，不自动创建 Human Decision、Replay 运行态、Account Ledger
或 Formal Decision。完整的盘中案例训练工作台仍是后续 Learning 产品扩展；本轮先完成 Domain/API 与轻量 UI 入口。

## Limits

本轮未实现系统级 Push、Linux 部署、Mini Program、PostgreSQL、V2A 重写、Windows Live Agent 或交易执行。
Formal ACK 链保持 Assisted；用户仍必须人工 ACCEPT，并在冻结 V2A 原生入口导入 ACK。

