# 当前通信 Contract

- Shell 仅组合四模块，注册准确路由；不存在 Learning/Research/Replay/Simulation/Decisions 产品入口。
- 数据观察与 Live：AgentClient → Agent 所有者查询/命令。正式来源固定 MARKET_AGENT / MARKET_DATA_AGENT，不恢复旧 Workspace。Session、股票、日期、事实版本与 available_at 保持原意。
- Live：按 symbol / tracking_session_id / trading_date 隔离事实、队列和成功水位。输入由 Engine 保证 available_at <= visible_through；去重、预算、不可变输入/意见、前后轮资格沿用现有规则。
- AI：adapters.ai.AdvisoryProvider（实际入口 adapters/ai/advisory.py）经隔离 worker 调用已配置 Provider。输入预算、请求审计、HTTP重试保护和模型选项不改变；不再 import/执行 Legacy Provider。
- Account：成功意见与 Frozen Input 经 PortfolioService 形成意图，经执行模式、证据、报价、风险、T+1、交易单位和费用校验。ADVISORY_ONLY 不自动成交。退役非Live账户仅供Owner证据维护，不再开放产品读取/选择。执行绑定使用版本CAS；Frozen Input保留account_id、account_state_version、policy_version、binding_version及source_namespace。实时MANUAL资格沿用原模式，历史不执行。暂停仅阻止新增风险；恢复不重放旧意图。
- 通知：正式 Live 已成功提交的 AUTO_EVENT、MANUAL、MANUAL_REANALYSIS 入持久队列；失败/测试/回放不推送。按 namespace / Opinion / chat / channel 防重，网络与分析/账户事务分离。
- 维护：GET 仅读状态；显式 Owner 验证可持久化证明，批次清理保护任务、账户证据、基准和水位。快照策略遵循已保存配置，不在页面 GET 触发删除。
- 历史：/api/history/bars 提供 DAY/WEEK/MONTH，端到端截止过滤；/api/history/analyses 只接受显式手动任务，HISTORY_EOD 独立上下文，无实时、账户或通知写能力。Schema 位于 contracts/history/bars.schema.json，说明见 HISTORY_BARS_API.md。源缓存 GET 可保存可重建缓存，不产生业务意见、任务或交易。

主要页面：/live、/data-observation、/account、/system。主要 API：/api/live/*、/api/data-observation/*、/api/accounts/*、/api/system/*。退役产品 URL 返回普通 404，不建立兼容运行框架。

组合账户API：GET/POST /api/accounts；GET/PUT /api/accounts/execution-binding；PUT /api/accounts/{id}/settings（带account_state_version）；POST /api/accounts/{id}/delete（confirmed=true）。创建要求name、idempotency_key、initial_capital和完整policy。旧ledger展示与旧policy直接写路由退出；Engine只在Owner内部使用。

## 本机运行控制（计划16）

GET /api/system/runtime：期望/实际状态、最近检查、恢复原因和进度。POST /api/system/runtime/control：allowlist action＋background/web/agent目标，可选expected_revision；返回排队操作，完成必须以status核实。同源Web接口转交本机令牌IPC，CLI使用同一System Owner。内部shutdown只用随机令牌、精确Host且无浏览器Origin；正常等待业务Owner安全收尾。

Live enable/disable持久化先于启动/停止，维护只暂停实际运行；恢复读取最新版本，不回写旧意图。首次断线Session发现使用真实启用时间排除旧事件，已建立的AUTO_POLICY_BOUNDARY和成功水位不重建。进程强制操作须匹配创建时间、实际程序、项目/根、实例与父子链；未知Provider/交易/通知结果不得自动重发。
