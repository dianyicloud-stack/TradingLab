> CURRENT · 2026-10-12 · STEP08A 已完成并通过用户审核；当前工程已采用独立干净 Git 历史。干净根基线为 `fb2002b24be524441a8d02d03ee8fa50d4298fcb`，本轮仅授权其直接子文档提交及本地审计。STEP08B 上传和 STEP08C 异机验收尚未完成，禁止自行执行。旧 STEP06/07 Commit 仅为历史来源，不是当前祖先；旧敏感历史和原始现场证据只在本地归档保留，禁止复制对象、合并或上传。

# TradingLab 开发、审核与交接规则

CURRENT · 2026-10-12 · 来源：[项目基线](docs/PROJECT_BASELINE.md)、[当前交接](docs/HANDOFF_CURRENT.md)、用户 STEP05 规则、STEP08A 审核与 STEP08B-1 本地文档提交授权。

## 开工与写入边界（CURRENT）

1. 每次先报告实际工作目录、任务目标、拟改文件和影响范围。当前唯一默认可写工程是 `<PROJECT_ROOT>`；原 TradingLab、Portable RC1、正式数据和 STEP01 备份只读。所有生成物留在本工程受控 `.dev/` 子目录。先检查路径及祖先不是链接，不能把终端目录切换当成会话工作区已切换。
2. 检查 Git 状态：先检测 `.git`（可能是文件）及仓库归属。若存在且本轮允许只读 Git，记录分支、Commit、工作树差异；若不存在，记录 NOT_INITIALIZED，仅在用户明确授权初始化且安全检查通过时运行 init。若本轮禁止所有 Git 命令，明确记录未执行 status，不以此声称工作树干净。不得隐式初始化、提交、推送、切分支或覆盖他人改动。
3. 开发前必读 [ARCHITECTURE](docs/ARCHITECTURE.md)、[DATA_OWNERSHIP](docs/DATA_OWNERSHIP.md)、[CONTRACTS](docs/CONTRACTS.md)，再读 PROJECT_BASELINE、DECISIONS、TEST_STATUS、HANDOFF_CURRENT 及其指定的最新独立交接。
4. 先回答六问：Domain；数据所有者；Fact/Runtime；写权限；通信 Contract；是否触及冻结协议。不明边界先取证，停止依赖该边界的写入。
5. 当前业务基线是 2026-09-26 单体 Web 四模块，附已审核迁移及两项 FIX；不是 Foundation v0.1 阶段。Foundation 是 HISTORICAL。Share/PWA/Exchange 和退役产品不可自动恢复；不自动开始下一迁移步骤、真实交易、Watcher 或其他产品计划。

## 业务与数据硬约束（CURRENT）

- `legacy/` 全部只读，禁止导入、执行或修改；包括备份、Schema、配置和缓存。仅允许静态读取和权威指纹校验。
- 禁止跨领域文件路径或数据库连接绕过 Contract。Shell 只组合，shared 不承载业务规则。Agent、Live、History、Account、System 按 Owner 写入。
- 任何时间回看数据、指标、Event、Handoff、AI 输入都必须在 Engine 满足 `available_at <= visible_through`；旧 Replay 约束仍约束相关保留代码/测试，不授权恢复 Replay 产品。
- Human Decision 和修订只追加，长期学习事实不依赖 Replay runtime 生命周期；这是保留的历史事实约束，不声明存在当前 Learning/Decisions 页面。账户账本不可改写，冻结意见不可覆盖。
- DEV 使用 TEST 身份、Fake Provider/通知和隔离数据；不得加载原正式 `.env`、访问正式账户或用真实服务做测试。Telegram 只接受本地私有授权精确匹配，非 USER 禁发；细节见 [授权说明](docs/TELEGRAM_LOCAL_CONFIG.md)。不得记录真实目标、密钥、控制 token、账户身份或旧对话原文。

## 质量与阶段门禁（CURRENT）

- 所有结论标为 CURRENT、HISTORICAL、DEPRECATED 或 UNVERIFIED，并附源码/测试/报告来源。实现存在、历史验收与本轮实测是三个不同结论。
- 问题必须分类为 BLOCKER、DEFER、ACCEPTED。BLOCKER 未关闭不得推进受影响阶段；其他独立工作可以继续。DEFER 必须有责任步骤、负责人角色和最迟节点，不能写“以后再说”。ACCEPTED 必须说明限制、依据和复核触发条件。登记在 [当前交接](docs/HANDOFF_CURRENT.md)。关闭须引用实际证据，保留历史记录。
- 禁止为通过测试删除断言、改变跳过条件、改写历史证据、降低隔离/权限/SHA 校验或无来源接受新基线。每个测试记录命令、解释器、cwd、隔离方式、退出码和实际数量；未运行写 NOT_TESTED，不能复制历史 PASS 冒充本轮。
- 验证基线为固定开发环境中的 `python -m unittest discover -s tests -v` 与 `python trading_lab.py --verify-baselines`。应在本工程 `.dev/` 新建隔离源码副本运行，设置固定 Node、TEMP/TMP 与 TEST/Fake 输入，禁止从原项目解释器执行。安全执行范例和最新结果见 [TEST_STATUS](docs/TEST_STATUS.md)。冻结检查必须使 V2A.1.2.1、V2A.1.2.2 均 PASS；差异返回 1。
- 每次业务变更必须评估 Portable 白名单、配置、依赖、进程/路径、数据兼容性及锁。先查 `portable-work/source-lock.json` 和构建器；README、ARCHITECTURE 等也已锁定。必要更新先报告影响与受控方案，经任务授权审计逐文件差异、新锁、构建与测试；旧锁/证据保留。不得关闭校验。未获相关授权时停止该锁定文件的修改。
- Codex 提供可复核证据与执行结果；用户和 ChatGPT 审核批准、决定阶段推进。用户批准某阶段不等于批准之后所有步骤或正式操作。

## 双 PC 首次接手（CURRENT）

依次确认本机实际仓库路径/版本 → 阅读本文件和 PROJECT_BASELINE → ARCHITECTURE 与 DECISIONS → TEST_STATUS 与 HANDOFF_CURRENT → 最新独立交接 → 校验本机固定 Python/Node 与依赖 → 检查 DEV/正式账户及服务隔离 → 提交中文接手摘要。第二台 PC 路径若不同，必须先由用户确认独立工程根，再按本机根执行；不得默许原正式项目可写。

摘要必须包含四模块业务边界、两类 Worker、版本证据、实际测试与 NOT_TESTED、BLOCKER/DEFER、下一步范围。没有环境制品就报告缺失，不回退全局 Python/Node。一次新对话知识演练不代表第二台实体 PC 环境验收。

## 每轮结束（CURRENT）

在 `docs/handoffs/` 新增独立报告，使用 [模板](docs/handoffs/TEMPLATE.md)，并更新 HANDOFF_CURRENT。记录目标、实际变更文件、原因、测试与证据、遗留问题/节点、Portable 兼容性、数据/依赖变更、实际存在的分支/Commit、下一 PC 建议和审核状态。不得覆盖上一轮报告或自行宣布用户验收。

仅文档任务也须校验引用、内容一致性、锁、敏感信息和保护目录；是否重跑业务测试必须诚实说明。STEP08B-1 仅允许白名单本地文档提交，父提交必须是已审核干净基线，不得 amend/rebase 或引入旧历史。当前尚未上传，不创建远程、不执行Push；STEP08B-2/STEP08C须另行审核授权。旧 STEP05/06 阶段的禁令或授权不替代当前边界。

Git 字节策略见 [GIT_BYTE_POLICY](docs/GIT_BYTE_POLICY.md)：`.gitattributes` 保留原字节，不执行批量 renormalize。锁定文件须同时核验工作文件与 Git Blob；不得为 Git 转换修改源码锁。历史STEP06首次提交的27处既有空白仅获当时限项接受，不适用于本轮或后续新改动。

## 当前发布与异机边界（CURRENT）

- 当前仍为2026-09-26单体Web业务基线，Live、数据观察、Account、System四模块；Node行情Worker与Python AI Worker分离。文档提交不建立新的业务基线或改变源码锁。
- 用户仅接受当前PC外部Kaspersky响应注入对GitHub Private纯源码迁移的限定风险；原严格console.error=0仍FAIL，不得隐藏错误。PC-B负责人须在异机验收结束前，使用锁定Playwright/Chromium、干净Profile和TEST/Fake完成独立页面/交互/重启复测。
- Runtime ZIP独立分发，不进普通Git；现有制品已锁定，本轮尚未发布远程附件。拟由未来Private仓库的独立Release附件提供，仓库Owner确认访问权限、固定版本/Hash及保留责任后单独发布；Setup目前只读取本地制品，不自动认证下载。
- 原工程归档为同盘回滚资料，不具备独立磁盘灾备能力；归档只读，禁止与新历史合并，禁止mirror/all refs上传。未来仅对获准的main明确上传，不包含Codex内部快照引用。
- 最新流程与Runtime Hash见[当前交接](docs/HANDOFF_CURRENT.md)及[STEP08B-1交接](docs/handoffs/20261012_STEP08B_1.md)。版本使用实际Git HEAD，不能将旧476文件数或历史测试结果视为后续提交的当前计数/结果。
