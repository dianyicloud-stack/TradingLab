# M2.2 Fast Advisory Loop + Live UX Simplification

## 产品边界

M2.2 将盘中 AI 意见与正式确认拆开。Fast Advisory 的目标是快速读取 V2A 已产生的市场事实并更新 Live 卡片；
Formal Decision / ACK Loop 继续承担人工确认、审计、ACK Import、Receipt 和正式 consume。

Fast Advisory 不执行交易，不创建 Human Review，不产生 pending ACK，不写 Workspace，也不推进 V2A Confirmed Cursor。

## 数据流

```text
V2A Workspace (read-only)
  -> Event / Observation / current state
  -> debounce aggregator or manual request
  -> Frozen Advisory Input + previous AdvisoryOpinion
  -> existing configured V2B Provider transport
  -> schema validation
  -> immutable AdvisoryOpinion
  -> Trading Lab Advisory Cursor
  -> latest Live Card / history
```

自动模式按股票持久化，默认关闭。一个或多个未分析 Event 首次出现后建立 pending aggregation；配置的 3–5 秒
窗口结束后只调用一次 AI。手动模式允许没有 Event 但已有更新 Observation/State 的分析；完全无新数据返回
`NO_NEW_ADVISORY_DATA`，用户可用明确的 `force=true` 再分析。

Frozen Input 保存 event/observation 上限、当前只读市场快照、源 Handoff 身份、输入 hash 和上一条意见。
Provider 调用期间的新数据不会修改它。成功且通过 JSON Schema 校验后，Opinion 和输入在同一事务中追加；
随后才更新 Advisory Cursor。Provider 失败或 Schema 失败不会推进 Cursor。

## UI

Live 默认每只股票一张卡，只展示最新 AdvisoryOpinion。卡片提供 Provider、Model、None/Low/High/Max、
Auto AI 与“立即获取AI意见”；历史意见按需展开。正式 Decision/ACK 区默认折叠。

Decisions 默认筛选今天、LIVE、每只股票最新 Formal Decision。HO、EHO、Correlation、ACK、Receipt、
Worker Generation 与 Hash 放入每条记录的“高级审计信息”。

Learning Case 删除使用不可变 tombstone。删除后的 Case 不再进入正常列表、筛选和训练入口；Shadow Account
成交账本仍由 Account Domain 保留，并在二次确认文案中明确提示。

## 存储与配置

- Fact：`data/decisions/advisory/advisory.db`
- Runtime：`data/runtime/live/advisory/advisory_runtime.db`
- Workspace：由 `TRADING_LAB_V2A_WORKSPACE` 配置，`pathlib.Path` 解析，业务代码无固定 Windows 路径。
- Provider/Model：从现有冻结 V2B 配置只读生成 catalog，实际请求复用既有隔离 Provider worker。

当前限制：M2.2 不提供“将 AdvisoryOpinion 转为 Formal Decision”的命令；需要正式闭环时继续使用原 Formal Loop。
