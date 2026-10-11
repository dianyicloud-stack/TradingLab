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
