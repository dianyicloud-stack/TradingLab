> CURRENT · STEP07-FIX 发布候选。原文中的 STEP06/07 提交与验收是历史来源，非本候选祖先或当前测试结论。最新适用状态见 `HANDOFF_CURRENT.md`；原始现场证据仅本地保存。

# 测试基线与适用限制

CURRENT · 2026-10-11 · STEP07。唯一被测HEAD `b306d13dee59f41c69ff9b4ff92a0d74dc5871ba`。本机双份真实克隆、恢复、回归及Portable重建完成；整体阶段因隐私发布门禁和浏览器控制台错误保留FAIL。第二台实体PC与GitHub网络克隆NOT_TESTED。原始记录不改写，当前结果见[STEP07报告](../STEP07_TradingLab干净克隆与恢复验收报告.md)。

| 范围 | 状态与实际结果 | 证据 |
|---|---|---|
| STEP07 两份clone/锁 | CURRENT PASS：autocrlf true/false，含中文空格路径；686文件与HEAD字节一致，246严格输入、81冻结文件匹配 | [A（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)、[B（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md) |
| STEP07 恢复/DEV/Portable | CURRENT PASS：两份Setup/重复Setup/Check、DEV/Portable启停重启及合成账户持久化；双份3631文件/149422503字节载荷一致 | [命令、cwd、解释器、退出码及日志Hash（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)、[双构建（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md) |
| STEP07 完整回归 | CURRENT PASS / SKIPPED：431项，418PASS、0FAIL/ERROR、13SKIPPED；退出0 | 原日志`.dev/step07/full-regression.log`，Hash及命令见[运行记录（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md) |
| STEP07 冻结及专项 | CURRENT PASS：冻结V2A.1.2.1/V2A.1.2.2和81文件；新Telegram15、部署14、独立合成补充7；退出均0 | [运行记录（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)、[13跳过逐项处置](migration/step07/SKIPPED_REVIEW.md) |
| STEP07 浏览器 | CURRENT FAIL：真实锁定Chromium四页、导航、账户创建/暂停/重启状态子项PASS；两轮pageerror0，但各5console.error来自被隔离的Kaspersky注入；未忽略错误 | [E2E证据（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)；丰富行情/全交互视觉矩阵NOT_TESTED |
| STEP07 进程保护 | CURRENT：未知子进程保护PASS；正常停止/失败回收PASS；通用force对实际DEV包装器安全拒绝，USER强停全矩阵NOT_TESTED | [未知子进程（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)、[实际拒绝（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md) |
| STEP07 上传隐私 | CURRENT FAIL：686Blob密钥复扫无未解决项，但历史账户目录/生产捕获路径等阻断公开上传 | [密钥扫描（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)、[元数据复核（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md) |
| STEP07 保护/边界 | CURRENT：保护根元数据前后一致；一次版本探针继承系统TEMP为待审核偏差，不能宣称整轮全部临时写入都在工程内 | [保护证据（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)、[报告](../STEP07_TradingLab干净克隆与恢复验收报告.md) |
| STEP03 初次回归 | HISTORICAL：431 项，417 PASS、1 FAIL、13 SKIPPED | [旧日志（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)；健康接口测试夹具缺 runtime |
| STEP03-FIX | HISTORICAL：431 项，418 PASS、0 FAIL/ERROR、13 SKIPPED | [修复报告](../STEP03-FIX_单元测试修复报告.md)；保留 HTTP 200 和并发断言 |
| STEP04-FIX 完整回归 | HISTORICAL / 当前已审核代码基线：431 项，418 PASS、0 FAIL/ERROR、13 SKIPPED | [完整日志（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md) |
| STEP04-FIX Telegram | HISTORICAL：原18、新安全15、候选包新安全15均 PASS | [原专项（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)、[新专项（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)；全部 Fake/Mock，不是真实消息 |
| STEP04-FIX Portable | HISTORICAL：14/14；两个3631文件候选逐项SHA相同，Check均PASS | [部署14（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)、[比较（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md) |
| STEP05 完整回归 | HISTORICAL：431 项，418 PASS、0 FAIL/ERROR、13 SKIPPED，退出码0 | [STEP05完整日志（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)；隔离副本，固定DEV解释器 |
| STEP05 冻结基线 | HISTORICAL：V2A.1.2.1、V2A.1.2.2 PASS；81文件不变 | [STEP05基线（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md) |
| STEP05 Check-Dev | HISTORICAL：PASS，退出码0；Python3.12.14、Node24.19.0、25依赖与隔离检查 | [环境检查（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md) |
| STEP05 文档/锁/保护/接手 | HISTORICAL：已通过阶段审核 | [STEP05报告](../STEP05_TradingLab项目知识与开发交接报告.md) |
| STEP06 Check-Dev | HISTORICAL：首次 Commit 前后两次 PASS、退出码均0；Python3.12.14、Node24.19.0、25依赖、3378 Runtime 文件完整性、TEST Worker/隔离/端口检查 | [STEP06运行记录（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)、[提交后输出（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md) |
| STEP06 Git/源码字节 | HISTORICAL：首次提交665文件全部 Blob 与工作文件相同，246严格输入SHA匹配；相反autocrlf配置的本地过滤转换也保持字节 | [Git审计（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)、[字节策略](GIT_BYTE_POLICY.md) |
| STEP06 完整回归/冻结命令/干净检出/重建 | HISTORICAL阶段的NOT_TESTED；不覆盖上方STEP07实际运行结果 | [STEP06报告](../STEP06_TradingLab本地Git初始化及安全审计报告.md) |

## 如何安全复验（CURRENT）

先确认独立工程、固定 Runtime 与 TEST 配置，按 [AGENTS](../AGENTS.md) 记录六问。已获干净恢复验证授权时，在工程`.dev/<本轮>/`建立真正独立Git克隆，核验HEAD/字节/属性后，用匹配ZIP在克隆内Setup恢复；不复制`.env`、`.env.telegram`、数据库、旧`.dev`或`.venv`。使用该克隆`.venv/Scripts/python.exe -B`，cwd为克隆，TEMP/TMP和Node均指向该克隆固定路径。环境按既有白名单，不继承真实密钥。STEP05普通隔离副本方案是历史验证方式，不能代替Git克隆验收。

在此上下文运行 `python -m unittest discover -s tests -v` 与 `python trading_lab.py --verify-baselines`；`python` 必须替换为上述已确认的解释器绝对路径。不要把这两行当成任意终端中调用全局 Python 的许可。STEP05 实际命令、cwd、退出码在 [runs.json（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)。Legacy 仅静态校验，不导入执行。

Portable 部署测试需要真实候选布局，不能直接在 authoring 根运行后把布局错误当业务缺陷。新授权专项在 `portable-work/tests/test_telegram_release_security.py` 单独发现；不加入原431计数。本轮没有改任何测试断言、跳过条件或生产代码。

HISTORICAL：STEP05 第一次通过临时驱动调用 Check-Dev 的命令包装返回语法错误（退出1），未进入实际检查；随后在本工程 PowerShell 直接调用原 Check-Dev.cmd 退出0。未改检查器/配置绕过错误；保留 [调用失败记录（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)，不把它记成业务回归失败。

## 限制（UNVERIFIED / ACCEPTED）

- 13 项私人生产捕获测试仍 SKIPPED，意味着完整原始捕获复现未完成，不等于431项全部通过。源码保留，安全输入另行审核。原始路径清单见 [未可用输入（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)。
- 新包第二台 Windows PC、真实 USER 全链、自然盘中影子成交、当前外部 AI/Telegram 投递未验证。旧RC1用户反馈、单机中文/空格路径、知识新对话均不能代替物理异机测试。
- STEP04 的隔离 Start/Stop、四页HTTP/静态资源、Agent/Worker、账户持久化、安全负例和恢复结果为历史实测；STEP04-FIX 没重跑完整 UI/生命周期矩阵。STEP05文档轮也不以启动正式服务补测。
- STEP07已取得锁定Playwright/Chromium并执行四页真实E2E，严格整体因外部安全软件注入报错FAIL；丰富行情视觉与全量交互仍NOT_TESTED。浏览器是另行授权的隔离测试制品，不在业务Runtime中，下一PC不会随Setup自动取得；当前Node制品不带npm。
- Runtime上游签名/远程认证下载、外层 ZIP 逐字节一致、生产迁移与灾备恢复、高级强停全矩阵、无人登录启动/睡眠/非Windows平台均有明确限制；责任节点见 [HANDOFF_CURRENT](HANDOFF_CURRENT.md)。

任何新 FAIL/ERROR 都必须先归因并记录；BLOCKER 未关闭不能推进受影响阶段。不得重新写旧日志，把历史417+1FAIL覆盖为现在418PASS。
