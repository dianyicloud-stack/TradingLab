> CURRENT · STEP07-FIX 发布候选。原文中的 STEP06/07 提交与验收是历史来源，非本候选祖先或当前测试结论。最新适用状态见 `HANDOFF_CURRENT.md`；原始现场证据仅本地保存。

# TradingLab 当前项目基线

CURRENT · 2026-10-11。产品基线是用户确认的 **2026-09-26 单体 Web**；工程附 STEP02—04、STEP03-FIX、STEP04-FIX 已审核迁移成果。STEP06 已在本地 main 建立首次 Git Commit `6d655308096abc69cc3f3cb8d8df855cc170b45d`，尚未上传 GitHub。该提交记录当前审核源码，不证明精确恢复历史；迁移前的提交链仍为 UNVERIFIED。来源：[STEP06报告（历史版本，本地保留）](https://github.com/dianyicloud-stack/TradingLab/blob/7b61c5c3c443d1a6889440efdf3a640d53e376b2/STEP06_TradingLab%E6%9C%AC%E5%9C%B0Git%E5%88%9D%E5%A7%8B%E5%8C%96%E5%8F%8A%E5%AE%89%E5%85%A8%E5%AE%A1%E8%AE%A1%E6%8A%A5%E5%91%8A.md)、[迁移报告（历史版本，本地保留）](https://github.com/dianyicloud-stack/TradingLab/blob/7b61c5c3c443d1a6889440efdf3a640d53e376b2/STEP04-FIX_%E5%8F%91%E5%B8%83%E5%AE%89%E5%85%A8%E6%95%B4%E6%94%B9%E6%8A%A5%E5%91%8A.md)、[证据来源](KNOWLEDGE_SOURCES.md)。

## 产品目标与边界（CURRENT）

数据观察 → AI 辅助判断 → 风控与影子账户。系统保留可追溯行情事实、冻结输入和意见，再按账户权限处理影子执行；不是已接入实盘券商的交易平台。四模块由 [bootstrap.py](../app/shell/bootstrap.py) 注册，边界测试为 [test_product_convergence.py](../tests/test_product_convergence.py)。

| 模块 | 已实现 | 边界与源码 |
|---|---|---|
| Live | 股票/Session 实时监听、自动事件分析、手动分析和明确重新分析、队列与冻结意见、执行账户摘要 | [advisory.py](../engines/live/advisory.py)、[router.py](../app/live/router.py)；查看/折叠不产生交易，成功之后才交 Account/通知 |
| 数据观察 | Agent 跟踪命令、观察表格与行情事实读取；日/周/月历史 K 线及截止日手动分析 | [observation.py](../app/live/observation.py)、[history.py](../app/live/history.py)；历史分析是独立 HISTORY_EOD，不写实时成功水位、账户和通知 |
| Account | 命名组合账户、创建幂等、账户设置、持久执行绑定、目标仓位、暂停新增风险、账本和投影 | [portfolio.py](../app/account/portfolio.py)、[engine.py](../engines/account/engine.py)；查看账户与 Live 执行账户不同，默认 ADVISORY_ONLY 不自动成交 |
| System | 数据源、AI 模型默认值、通知状态、维护、运行控制 | [module.py](../app/system/module.py)、[bootstrap.py](../app/shell/bootstrap.py)；状态页面不是数据库后门，不对外暴露本机控制凭据 |

## 核心业务规则（CURRENT，指实现，不宣称本轮真实市场验收）

- **行情**：唯一正式事实源 MARKET_AGENT / MARKET_DATA_AGENT。Python Agent Owner 通过固定 Node Worker 执行原生算法、落库及发布；Web 经认证 Contract 读取/命令，不直连 Agent SQLite。行情实际可用性取决于来源与交易时段，不能把进程健康等同于有新事实。见 [Agent service](../engines/live/market_agent/service.py)、[AgentClient](../bridges/market_agent.py)、[来源配置](../adapters/source_configuration.py)。
- **时间与分析**：按 symbol / tracking_session_id / trading_date 隔离；Engine 做截止边界、事实资格与预算，输入/意见不可变。Live 同股串行、多股池上限 8；History 池上限 2。模型/配置随任务冻结，切换当前默认值不改写旧任务。见 [advisory.py](../engines/live/advisory.py)、[history/service.py](../engines/history/service.py)、[capabilities.py](../adapters/ai/capabilities.py)。
- **AI**：独立 Python Worker 调用已配置 Provider；结构化输出失败、截断或未知结果不能伪造成功。配置支持 DeepSeek/OpenAI 适配，但本轮不验证任何供应商当前线上模型/价格/可用性；历史真实调用记录仅为 HISTORICAL。见 [transport.py](../adapters/ai/transport.py)、[AI_PROVIDER_15.md](AI_PROVIDER_15.md)。
- **影子账户**：OFF / ADVISORY_ONLY / AUTO_SHADOW_EXECUTION，不能替用户开启自动模式。成功意见经绑定与状态版本、证据、报价、风控、交易单位、费用、T+1 等校验；OPEN/ADD/REDUCE/EXIT 按目标差额处理，冲突拒绝。暂停阻止新增风险，恢复不重放旧意图。规则只覆盖代码支持的普通沪深北 A 股，当前日历仅 2025/2026，未知年份拒绝。这里记录代码实现，不是交易所最新规则认证。见 [rules.py](../engines/account/rules.py)、[control.py](../engines/account/control.py)、[test_user_portfolios.py](../tests/test_user_portfolios.py)。
- **通知**：只有正式 Live 成功的 AUTO_EVENT、MANUAL、MANUAL_REANALYSIS 进入独立队列，去重与未知结果保护保留。目标必须匹配本机 `.env.telegram` 授权；空模板无授权，DEV/TEST 禁发。见 [本地配置](TELEGRAM_LOCAL_CONFIG.md)、[notifications.py](../app/system/notifications.py)。
- **历史保留**：History 当天列表引用原 Opinion；上海本地日 TTL 次日及启动补清理，保护运行任务/设置，不改实时/账户/通知保留策略。见 [history/store.py](../engines/history/store.py)、[HISTORY_RESULTS_ACCEPTANCE.md](HISTORY_RESULTS_ACCEPTANCE.md)。

## 数据与工程版本（CURRENT）

Owner、写入顺序、账本与 Fact/Runtime 见 [DATA_OWNERSHIP](DATA_OWNERSHIP.md)、[CONTRACTS](CONTRACTS.md)、[架构补充](ARCHITECTURE_CURRENT.md)。`data/runtime` 含恢复水位，不是可统一清空的缓存。不得从文件存在推断产品有效或有权删除。

固定环境：Python **3.12.14 x64**、Node **24.19.0**、25 项 Python 依赖；锁为 [dev/runtime-lock.json](../dev/runtime-lock.json)、[requirements-lock.txt](../requirements-lock.txt)。Portable 候选输入锁版本 `step07-fix-20261011.1`，SHA-256 `89bbf8471108a55f2b129ab41c14735865ffbaf77df7f51a621108a225612990`，见 [source-lock.json](../portable-work/source-lock.json)。它不是 Git Commit。

## 当前开发入口（CURRENT）

取得完整源码和匹配 SHA 的 Runtime ZIP（当前需要可信渠道单独提供），在独立工程根依次使用 `Setup-Dev.cmd`、`Check-Dev.cmd`，需要开发运行时再 `Start-Dev.cmd`，结束用 `Stop-Dev.cmd`。DEV 为 TEST 身份，默认 Web 18765、Agent 18766；隔离数据 `.dev/data` / `.dev/agent`，真实行情网络、AI 和 Telegram 禁用。无 npm/全局 Python 依赖；浏览器 E2E 需另行取得锁定工具，不是已自动完成。详见 [开发说明](../dev/README.md)；其中旧 FAIL、旧构建问题和隐私风险状态以 [TEST_STATUS](TEST_STATUS.md) 与最新交接为准。

`Build-Portable.cmd` 从固定 ZIP 与白名单/锁离线构建新的 `.dev` 候选，目标存在则拒绝覆盖。默认候选为 TEST，不等于批准正式 USER 迁移。新候选具有 Start/Stop/Check。旧 RC1 是只读历史，不更新覆盖。详见 [构建说明](../portable-work/PORTABLE_README.txt)。

根 [README.md](../README.md) 与 [ARCHITECTURE.md](ARCHITECTURE.md) 已审核保留，不改其构建哈希。README 的桌面/8765/重启/实发工具说明属于既有 USER 使用背景，**不是本工程 DEV 接手流程**；Telegram 还必须满足新的私有授权。不要执行历史说明来恢复旧服务。新知识文档不收录进当前 Portable 运行白名单。

## 退役与未知（DEPRECATED / UNVERIFIED）

DEPRECATED：Share/PWA/Exchange 后续实验不属于当前基线；Learning、Research、独立 Decisions、Replay/Simulation 产品、Formal Handoff/ACK 执行入口和旧 Workspace 正式来源不恢复。Legacy 的字词/Schema 和 TEST 支持存在不证明产品存在。证据：[ARCHITECTURE](ARCHITECTURE.md)、[test_product_convergence.py](../tests/test_product_convergence.py)、用户 STEP05 范围。

UNVERIFIED：首次本地 Git 基线之前的精确提交历史、未读取的更早对话、第二台实体 PC 新包验收、当前真实 AI/通知/自然盘中执行状态。全部跟踪于 [HANDOFF_CURRENT](HANDOFF_CURRENT.md)，不得凭旧部署记录更新为 CURRENT PASS。Git 原字节保护的本地结果见 [GIT_BYTE_POLICY](GIT_BYTE_POLICY.md)；干净克隆、环境恢复和 Portable 重建仍待 STEP07/08 授权验证。
