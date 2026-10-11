> CURRENT · STEP07-FIX 发布候选。原文中的 STEP06/07 提交与验收是历史来源，非本候选祖先或当前测试结论。最新适用状态见 `HANDOFF_CURRENT.md`；原始现场证据仅本地保存。

# 主要决策与适用范围

CURRENT 文档索引 · 2026-10-11。这不是补造 Git ADR 时间线。日期来自原文件标题或可访问会话；“当前有效”必须另有源码支持。

| 决策 | 状态 | 理由、边界与证据 |
|---|---|---|
| 2026-09-26 单体 Web 为业务基线 | CURRENT | 用户指定，当前四模块注册一致；[PROJECT_BASELINE](PROJECT_BASELINE.md)、[bootstrap](../app/shell/bootstrap.py)。无精确 Git commit 来源证明 |
| 四模块收敛，Shell 只组合 | CURRENT | 减少并行产品和跨 Owner 写入；[ARCHITECTURE](ARCHITECTURE.md)、[test_product_convergence](../tests/test_product_convergence.py) |
| 独立 Agent 是唯一正式行情来源 | CURRENT | 行情 Owner 独立生命周期，保留原生计算，Web 经 Contract；[source_configuration](../adapters/source_configuration.py)、[market_agent/service](../engines/live/market_agent/service.py) |
| 输入和意见冻结，Engine 截止边界 | CURRENT | 防未来数据与任务配置漂移；[advisory](../engines/live/advisory.py)、[history/service](../engines/history/service.py)、[CONTRACTS](CONTRACTS.md) |
| 用户组合与 Live 执行绑定分离 | CURRENT | 查看不等于执行授权，CAS/状态版本防串账；[portfolio](../app/account/portfolio.py)、[USER_PORTFOLIOS_7_11](USER_PORTFOLIOS_7_11.md) |
| AI Provider 保持 Adapter + 隔离 Worker | CURRENT | 模型选择热生效只影响新任务；失败不伪成功；[capabilities](../adapters/ai/capabilities.py)、[AI_PROVIDER_15](AI_PROVIDER_15.md) |
| 历史分析不向 Account/通知/实时水位写入 | CURRENT | 回看不可触发现实执行；[bootstrap](../app/shell/bootstrap.py)、[HISTORY_RESULTS_ACCEPTANCE](HISTORY_RESULTS_ACCEPTANCE.md) |
| Supervisor 管生命周期，Owner 管收尾 | CURRENT | 监听意图持久化，未知结果不强制自动重发；[runtime_control](../app/system/runtime_control.py)、[RUNTIME_16_WINDOWS](RUNTIME_16_WINDOWS.md) |
| 2026-09-26 关闭 Windows 登录自动启动 | HISTORICAL | [WINDOWS_ENTRIES](WINDOWS_ENTRIES.md) 与已读旧会话有记录；当前机器任务状态未重新查询，不宣称永久关闭或移植后已配置 |
| 固定 Runtime + ZIP 内容锁 + 独立 DEV | CURRENT | 不依赖旧 PC .venv/Node/global；[dev/README](../dev/README.md)、[runtime-lock](../dev/runtime-lock.json)、[STEP03报告](../STEP03_TradingLab统一开发环境报告.md) |
| Portable 白名单，禁止构建时改业务文件 | CURRENT | 受控输入、拒绝覆盖、保留新旧锁；[builder](../portable-work/build_portable.py)、[STEP04报告](../STEP04_TradingLabPortable自动构建报告.md)；UTF-8 修复已在统一源码 |
| Telegram 单一目标授权迁到本地私有 dotenv | CURRENT | 缺省拒绝、非 USER 禁发、不接受 Web/环境授予授权；[TELEGRAM_LOCAL_CONFIG](TELEGRAM_LOCAL_CONFIG.md)、[STEP04-FIX](../STEP04-FIX_发布安全整改报告.md) |
| Foundation、Replay、正式 Handoff/ACK、早期 Watcher 设计 | HISTORICAL / DEPRECATED | 历史设计保存，当前产品入口退役；[FOUNDATION_V01_FROZEN](FOUNDATION_V01_FROZEN.md)、[旧ADR目录](adr)、[当前架构](ARCHITECTURE.md)。保留未来数据与事实不可变约束，不恢复产品 |
| 9月26日后 Share/PWA/Exchange 方案 | DEPRECATED | 用户明确排除；已发现归档会话但未完整读取其正文，不补写全部否决原因或撤回提交 |
| 新知识放在锁外 docs，保留锁定 README/架构原文 | CURRENT | STEP05 仅知识治理，不更改运行制品输入；新入口由 AGENTS 与 PROJECT_BASELINE 提供；[源码锁](../portable-work/source-lock.json) |
| 本地Git新基线与原字节策略 | CURRENT | STEP06首次Commit `6d655308096abc69cc3f3cb8d8df855cc170b45d`，main且无远程；根属性禁止内容转换，665初始Blob与246严格输入逐项一致。既有27处空白和公开行情参数为用户限项确认，不修改源码锁；[STEP06报告](../STEP06_TradingLab本地Git初始化及安全审计报告.md)、[字节策略](GIT_BYTE_POLICY.md) |

UNVERIFIED：恢复基线的精确提交、后续实验完整因果链、当前外部 API 模型能力/价格、自然盘中真实成交状态。不得用历史表述替代重新验收。
