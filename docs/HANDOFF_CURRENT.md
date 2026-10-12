# STEP08B-1 首次上传前当前交接

CURRENT · 2026-10-12 · STEP08A 已完成并通过用户与 ChatGPT 审核；本轮只做知识整理、一个本地文档提交及上传前审计。最新[独立交接](handoffs/20261012_STEP08B_1.md)。**尚未创建GitHub远程、上传源码或发布Runtime；STEP08B-2、STEP08C未完成。**

干净根基线为 `fb2002b24be524441a8d02d03ee8fa50d4298fcb`；本轮文档提交只允许以它为直接父提交，不amend/rebase、不导入旧对象。当前完整HEAD通过 `git rev-parse HEAD` 获取，并在本地最终审计报告记录，避免提交自引用。最终文件数和清单SHA重新计算，旧476仅适用于根基线。

业务继续采用2026-09-26单体Web四模块，Owner、Contract、时间边界及两类Worker不变。235业务输入、11构建输入、81冻结文件、Portable能力和原13 SKIPPED条件不变。历史原main、旧首次提交、否决v1及原始私人证据禁止上传；旧归档只读离线保留，同盘回滚不是独立灾备。

STEP08A已实测新根Setup/Check/Start/Stop及TEST Web-Agent-Node通信通过。它们是已审核阶段结果，不冒充STEP08B-1重新运行；本轮实际检查以`.dev/step08b-1/`最终报告、Check日志、暂存与HEAD审计记录为准。完整431回归、Portable重建、浏览器E2E和生产模式本轮NOT_TESTED。

| 编号 | 分类 | 当前要求、负责人及最迟节点 |
|---|---|---|
| C08A | CLOSED | 旧根归档与干净来源切换已获用户审核；STEP08A交接保留具体结果 |
| A08B-01 | ACCEPTED 限定 | Private纯源码迁移可按用户限定接受推进；当前PC严格console.error=0仍FAIL，未改判。公开发布、第一方异常或范围改变须重新审核 |
| D08B-01 | DEFER | PC-B操作者/验证负责人最迟异机验收结束前完成锁定浏览器、干净Profile四页/交互/重启复测，保留pageerror及全部console.error，不关闭防护或放行未知请求 |
| D08B-02 | DEFER / 发布前门禁 | 用户与发布负责人在STEP08B-2执行前确认最终HEAD、Private仓库Owner/名称/空仓库URL、凭据权限及明确Push授权；当前未获网络写入许可 |
| D08B-03 | DEFER | Runtime负责人在PC-B恢复前发布独立Private Release附件、核验下载权限和SHA；当前本地有制品，远程未发布，下载链接尚不存在 |
| A08B-02 | ACCEPTED | 13私人捕获SKIPPED和同盘归档限制沿用；相关算法改变或磁盘风险时由数据Owner/归档管理员复核 |
| D08B-04 | DEFER | USER高级强停全矩阵、真实AI/Telegram、生产模式和正式数据迁移在使用前独立授权与验收；未知子进程保护不放宽 |

固定制品：`tradinglab-dev-runtime-win-x64-20261011.1.zip`，SHA-256 `3ffc1c0fc14a7e461f4acc8cc8453cb73ff8d62afecfd7cc9234e6c6981f0f0e`。计划作为未来GitHub Private仓库的独立Release附件，不进入Git；Release标签必须指向新干净历史的获准Commit，不使用旧标签或旧历史。Owner负责长期保留、两PC访问和重新下载校验，不承诺永久在线可用。Setup不含认证下载器：PC-B先取得ZIP并验证Hash，再放本工程`.dev/artifacts/`后运行入口。

PC-B顺序：确认独立工程根/获准Commit → 阅读AGENTS、PROJECT_BASELINE、ARCHITECTURE、DECISIONS、TEST_STATUS和本交接 → 取得并核验Runtime → Setup/Check → TEST DEV启停和Web/Agent/Worker → 锁定浏览器E2E → 回归/冻结/专项 → Portable构建及运行 → 明确文件白名单和反向Git交接。不存在“本机恢复等于异机已通过”的推论。

本轮最终报告留本地`.dev/step08b-1/`，新增文档不含现场绝对路径、密钥或生产捕获。是否允许STEP08B-2由用户与ChatGPT审核决定，Codex只报告技术条件并停止。

---

## HISTORICAL：以下为STEP08A及此前交接原文

以下“等待审核”“未提交”等描述指当时状态，以本节上方2026-10-12当前状态为准；原记录不追溯改写。

# STEP08A 当前权威来源已切换

CURRENT · 2026-10-11 · 最新[独立交接](handoffs/20261011_STEP08A_SWITCHED.md)。以下STEP07-FIX候选原文保留为历史，不再代表尚未提升的当前状态。

- 用户已审核v2隐私/恢复并授权STEP08A同盘归档和切换。当前权威根为本工程，main HEAD `fb2002b24be524441a8d02d03ee8fa50d4298fcb`；独立干净历史，无旧main/首次提交/v1祖先，无远程或上传。
- CURRENT PASS：476基线文件与Blob、534对象、235/11输入及81冻结指纹；旧归档129351文件完整复核；新根Setup/Check/Start/Stop均退出0，TEST Web-Agent-Node Worker通信通过且已正常停止。全量证据仅本地 `.dev/step08a/`。
- 四模块业务、Owner/Contract和两类Worker边界不变。本轮只恢复新TEST数据，未复制旧环境/正式配置/数据库；未修改业务、Legacy、测试或锁。
- A08A-01：用户接受同盘回滚，非独立磁盘灾备；旧历史离线保留、不得合并上传。A08A-02：用户仅接受当前PC注入对Private纯源码迁移的限定影响，严格console.error=0仍FAIL；PC-B负责人最迟异机验收结束前独立复测。
- 原13 SKIPPED、未知进程保护、USER/生产/真实服务NOT_TESTED保留。本轮431回归、Portable重建、浏览器E2E未重跑，历史结果不冒充当前PASS。
- D08A-02：发布负责人首次上传前审核并单独提交本轮三份交接/测试文档、确认Private目标与Runtime分发；当前未暂存、未提交。技术后验结束时工作树clean，交接写入后仅这三份已解释文档差异。
- STEP08A技术验证完成，等待用户与ChatGPT最终审核；可提请STEP08B审批，不构成上传授权。完成后建议解除备份根的项目附加引用，保留磁盘文件。

---

# 发布候选当前交接

CURRENT · STEP07-FIX · 候选 Git 在本目录独立建立，旧工程两个 Commit 不作祖先。以 `git rev-parse HEAD` 获取当前完整版本；提交建立后无需通过自引用改写本文件。尚未上传，等待用户与 ChatGPT 审核。

最新独立交接：[STEP07-FIX](handoffs/20261011_STEP07_FIX_CANDIDATE.md)。旧报告的同名摘要均为派生说明，原件仅本地保存。读 [证据范围](RELEASE_EVIDENCE_SUMMARY.md)、[项目基线](PROJECT_BASELINE.md)、[当前架构](ARCHITECTURE_CURRENT.md)、[数据所有权](DATA_OWNERSHIP.md)、[合同](CONTRACTS.md) 后开始开发。

业务仍为 2026-09-26 单体 Web 四模块。两类 Worker 分离，时间与写入 Owner 约束不变。DEV 固定 Python 3.12.14、Node 24.19.0、TEST/Fake、本工程隔离数据；Runtime ZIP 不入 Git。禁止 Legacy 执行、正式账户和通知。

候选锁 `step07-fix-20261011.1`：经用户批准，仅两份冻结历史说明脱敏并更新两个 Hash；235/11 文件集和 81 Legacy 未删减。部署专项精确差异集合增加两个文档；13 个原始跳过条件不变，未知进程保护不变。

本候选当前实测以独立 STEP07-FIX 报告为准，不能把旧 STEP07 431/418/13 复制成当前 PASS。源代码历史文档保留时态提示，不授权旧 USER 操作。

| 编号 | 分类 | 状态与关闭节点 | 责任 |
|---|---|---|---|
| B07-01 | BLOCKER 待审核 | 候选隐私整改提交全历史/Blob 验收；原历史继续禁止发布；任何上传前审核 | 发布负责人、用户/ChatGPT |
| B07-02 | BLOCKER | 本机外部注入来源专项复验，严格零 console.error 未自行豁免；STEP08 前决定干净 VM/另一 PC 或限定风险接受 | 验证负责人、用户/ChatGPT |
| A01 | ACCEPTED 既有例外 | 13 私有捕获依赖保留 SKIPPED；变更相关算法或声称生产复现前补合法原证据 | 数据 Owner |
| A02 | ACCEPTED 限项 | 公开行情 ut 参数、必要许可证、用户指定作者身份保留；内容/用途变化重新审核 | 用户、发布负责人 |
| D01 | DEFER | 第二实体 PC、USER 强停、真实服务、正式数据迁移未验；使用对应能力前完成独立授权验收 | 目标 PC 操作者、运行/数据 Owner |
| R07-01 | DEFER 待审核 | STEP07 早期浏览器探针系统 TEMP 偏差仍保留；本轮控制所有浏览器 TEMP，不追溯改写原记录 | 用户/ChatGPT，本轮审核 |

后续提升必须单独授权，保留旧工程及 .git 回滚副本；不直接替换权威历史，不 push。
