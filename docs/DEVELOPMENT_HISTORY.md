> CURRENT · STEP07-FIX 发布候选。原文中的 STEP06/07 提交与验收是历史来源，非本候选祖先或当前测试结论。最新适用状态见 `HANDOFF_CURRENT.md`；原始现场证据仅本地保存。

# 有证据的开发历史

HISTORICAL · 整理于 2026-10-11。以下为文件/会话所能证明的阶段，不是提交级完整年表。2026-09-26 之后被废弃的实验不计入现有产品。

| 时间 / 阶段 | 有证据的变化 | 来源与当前适用性 |
|---|---|---|
| Foundation v0.1 / 早期 Replay | 分域、冻结基线、未来数据防护、历史 Replay/Watcher/ACK 设计 | [FOUNDATION_V01_FROZEN](FOUNDATION_V01_FROZEN.md)、[VALIDATION](VALIDATION.md)、[ADR](adr)。HISTORICAL；相关产品 DEPRECATED，冻结保护仍 CURRENT |
| 2026-09-09 至 09-18 M2/Agent | 早期 Advisory 演进、原生 Agent 抽取、正式来源收敛与自动分析闭环 | [M2_CURRENT_STATE_AUDIT](M2_CURRENT_STATE_AUDIT.md)、[MARKET_DATA_AGENT](MARKET_DATA_AGENT.md)、[M2_AUTO_AGENT_CLOSURE](M2_AUTO_AGENT_CLOSURE_20260918.md)。不沿用旧 Workspace 默认来源说明 |
| 2026-09-21 至 09-23 | 数据生命周期、读取稳定性、保留阻断修复 | [DATA_LIFECYCLE](DATA_LIFECYCLE_20260921.md)、[RETENTION_BLOCKER_FIX](RETENTION_BLOCKER_FIX_20260923.md)。历史现场与未清理数据不等于当前授权删除 |
| 2026-09-25 前后四模块收敛 | Learning/Research/Decisions/Replay等退出；意见归 Live、账户证据归 Account、Provider 独立 | 已读旧主会话的收敛轮次；当前 [ARCHITECTURE](ARCHITECTURE.md)、[test_product_convergence](../tests/test_product_convergence.py)。精确 commit UNVERIFIED |
| 2026-09-25 History 与计划7—11、15 | 历史分析与当日结果、用户组合/绑定/目标仓位/风险暂停、模型能力与任务配置冻结 | [HISTORY_RESULTS_ACCEPTANCE](HISTORY_RESULTS_ACCEPTANCE.md)、[USER_PORTFOLIOS_7_11](USER_PORTFOLIOS_7_11.md)、[AI_PROVIDER_15](AI_PROVIDER_15.md)；旧主会话对应轮次交叉佐证 |
| 2026-09-26 计划16与桌面入口 | 独立 Supervisor、意图恢复、统一启停状态入口，随后关闭登录自启 | [RUNTIME_16_WINDOWS](RUNTIME_16_WINDOWS.md)、[WINDOWS_ENTRIES](WINDOWS_ENTRIES.md) 与已读旧主会话。旧现场运行状态仅 HISTORICAL |
| 9月26日后实验线 | Share/PWA/Exchange 被当前用户范围排除 | DEPRECATED；归档仅发现，完整实现/回退原因 UNVERIFIED，不纳入主链 |
| 2026-10-09 至 10-10 RC1 / 审计 | 便携 Runtime、14 项部署、差异和恢复计划；用户曾确认 RC1 基本异机运行 | [RC1验证](portable/rc1/验证报告.md)、[便携审计](portability-audit-20261010/开发版与%20Portable%20完整差异报告.md)、已读旧主会话。旧RC1不替代新包异机测试 |
| 2026-10-10 STEP01/02 | 609 静态文件保护；统一源码与工具/测试整合；单项 PowerShell UTF-8 兼容修复 | [STEP02](../STEP02_TradingLab统一源码整合报告.md)、其 STEP01 校验证据；本轮未重做备份 |
| 2026-10-11 STEP03 / FIX | 固定Python/Node/25依赖、隔离DEV；HTTP健康夹具补 `runtime=None` | [STEP03](../STEP03_TradingLab统一开发环境报告.md)、[STEP03-FIX](../STEP03-FIX_单元测试修复报告.md)。旧1 FAIL保留，FIX后418通过/13跳过 |
| 2026-10-11 STEP04 / FIX | 白名单自动构建、重复构建/恢复验证；Telegram本地私有授权与安全测试 | [STEP04](../STEP04_TradingLabPortable自动构建报告.md)、[STEP04-FIX](../STEP04-FIX_发布安全整改报告.md)。最新包3631文件，不改旧3630/RC1指纹 |
| 2026-10-11 STEP05 | 知识索引、质量门禁、双PC交接与独立接手演练 | HISTORICAL，用户已确认阶段审核；见 [STEP05报告](../STEP05_TradingLab项目知识与开发交接报告.md) |
| 2026-10-11 STEP06 | 本地main首次Git基线、白名单/实际Blob扫描及原字节保护 | CURRENT，首次Commit `6d655308096abc69cc3f3cb8d8df855cc170b45d`；[STEP06报告](../STEP06_TradingLab本地Git初始化及安全审计报告.md)。未上传GitHub，STEP07/08未执行 |

UNVERIFIED：缺页和私有证据见 [KNOWLEDGE_SOURCES](KNOWLEDGE_SOURCES.md)。原始迁移报告、锁、测试记录和旧 ADR 原样保留，新的摘要不能替换原始证据。
