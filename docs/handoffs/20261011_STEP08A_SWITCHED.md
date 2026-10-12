> CURRENT 审核补充 · 2026-10-12：用户已确认STEP08A通过审核，目录切换及新根恢复阶段已完成。下方2026-10-11报告原文保留为历史实测；“待审核/未提交/未进入STEP08B”是当时状态。本文件随获授权的STEP08B-1文档提交整理，未据此授权GitHub写入。最新状态见[当前交接](../HANDOFF_CURRENT.md)及[STEP08B-1](20261012_STEP08B_1.md)。
>
> 干净根基线仍为 `fb2002b24be524441a8d02d03ee8fa50d4298fcb`；仅文档直接子提交，不混入旧main/首次提交/v1历史。原严格console.error=0仍FAIL，Private纯源码迁移限定接受及PC-B复验要求不变。Runtime拟用未来Private Release独立附件，当前未发布；STEP08B-2与STEP08C未完成。

# STEP08A 干净 Git 来源切换后交接

CURRENT · 2026-10-11 · 执行者：Codex · 等待用户与 ChatGPT 审核。工程根为用户确认的 `<PROJECT_ROOT>`；本地完整路径与私有归档清单仅在受控证据中保留。

## 目标、范围与实际变更

旧工程已整体同盘改名归档，包含原 `.git`、未提交报告、隐藏文件、整个 `.dev`、Runtime、DEV 数据和测试证据。以独立干净检出提升至权威开发根，main HEAD 为 `fb2002b24be524441a8d02d03ee8fa50d4298fcb`；无旧提交祖先、无远程、无上传。归档只是同盘回滚，不具备独立磁盘灾备能力。

六问：Domain 为迁移控制及 DEV 恢复；业务数据仍属原 Owner；旧证据为保留事实，新 TEST 数据及会话快照为本地运行数据；仅工程生成目录和本次交接文档可写，旧归档及外部保护根只读；服务通过原有 Web/Agent Contract；不修改冻结协议、Legacy、业务实现或源码锁。

本轮新建本交接，更新 HANDOFF_CURRENT、TEST_STATUS；这些文档不在 Portable 输入锁中。Runtime ZIP、环境、日志、审计脚本和完整本地报告留 `.dev/step08a` 或原外部控制目录，不进普通 Git。476 个基线文件先通过全量核验；随后仅这三份文档形成待审核工作树差异，未暂存、未提交。

## 验证与证据

CURRENT 本轮：

| 项目 | 实测结果 | 本地证据 |
|---|---|---|
| Git 来源 | PASS：476跟踪文件、4950966字节，全部工作文件/HEAD Blob/SHA一致；534对象与已审核对象逐项相同；旧敏感提交不存在；fsck退出0 | `.dev/step08a/source-postcheck.json` |
| 字节和锁 | PASS：235业务输入、11构建输入、81冻结文件；V2A.1.2.1与V2A.1.2.2指纹PASS；原字节属性保留 | 同上 |
| 同盘切换 | PASS：外部独立PowerShell执行两次改名，退出0；旧根完整保留，新根为干净检出 | 外部控制目录的switch-state、追加journal及成功日志；不发布现场原件 |
| 旧归档 | PASS：129351文件、12508目录、5581814164字节，逐文件SHA及大小/时间/属性与离线清单一致，无链接 | `.dev/step08a/archive-postcheck.json` |
| Runtime | PASS：固定ZIP SHA匹配，Setup-Dev.cmd退出0；全新环境，不复制旧环境或数据 | `setup-result.json`、`setup.log` |
| 开发检查 | PASS：Check-Dev.cmd退出0，Python3.12.14、Node24.19.0、25依赖、3378Runtime文件及Worker检查通过 | `check-result.json`、`check.log` |
| DEV启停 | PASS：Start-Dev.cmd、Stop-Dev.cmd退出均0；Web/Agent为TEST；正常退出后Worker消失、端口空闲，无强停 | `lifecycle-runs.jsonl`、`stop-verification.json` |
| 通信 | PASS：合成TEST跟踪命令经过Agent与固定Node Worker，Web读取到同一记录；四页面HTTP200 | `integration.json`；不是浏览器E2E |
| 外部保护根 | PASS：原工程、RC1、STEP01、正式Agent数据的文件元数据指纹与准备阶段一致；不打开正式数据库 | `protected-postcheck.json` |

以上文件均位于 `.dev/step08a/`，是只留本地的现场证据。独立PowerShell是Windows自带5.1；Setup启动固定 `.dev/runtime/python/python.exe`，其余入口使用新 `.venv/Scripts/python.exe -I -B -X utf8`。cwd为权威工程；TEMP/TMP在工程内；入口建立清洁进程环境，TEST/Fake、禁行情网络/真实AI/Telegram。具体命令、cwd、退出码和时长保留于运行记录。

HISTORICAL：此前v2的431项为418 PASS、13 SKIPPED、0 FAIL/ERROR，用户已审核；本轮未重跑431项、完整Portable重建或浏览器E2E，不将历史PASS写成本轮结果。当前四模块为Live、数据观察、Account、System；Node行情Worker与Python AI Worker分离，本轮未启动真实AI Worker。

诊断历史保留：早期窗口被应用进程阻断；在线Git快照变化导致旧清单数量失效，现改为应用退出后生成离线最终封印。初始清单、失败日志、被应用替换的原快照引用字节均另行保全。后验临时扫描器曾将已审核的Runtime JSON指纹清单误识别为Runtime载荷，修正分类后全量复验PASS；无产品源码修复、无新增业务测试FAIL。

## 遗留事项与阶段门禁

| 编号 | 分类 | 限制、责任与复核节点 |
|---|---|---|
| A08A-01 | ACCEPTED | 用户明确接受同盘回滚归档；无独立灾备。归档管理员在磁盘异常或未来清理前重新评估；不得删除原归档 |
| A08A-02 | ACCEPTED 限定范围 | 用户仅接受当前PC外部Kaspersky注入对GitHub Private纯源码迁移的限定风险；严格console.error=0仍FAIL。公开发布、第一方异常或范围变化须重新审核 |
| D08A-01 | DEFER | PC-B操作者/验证负责人在异机验收完成前，使用锁定浏览器独立复测四页、交互、重启和原始错误日志；本轮NOT_TESTED |
| D08A-02 | DEFER | 发布负责人在首次上传前审核并单独提交本次交接文档、确认Private目标与Runtime私有分发；不得上传旧归档、旧refs或使用mirror推送 |
| A08A-03 | ACCEPTED 既有限制 | 原13个私有捕获SKIPPED不改；数据Owner在修改相关算法或声明原样本复现前取得合法证据 |
| D08A-03 | DEFER | USER高级强停全矩阵、生产模式及真实服务不在本轮范围，运行/数据Owner使用前需单独授权与验收；未知进程保护不放宽 |

B07-01发布候选隐私与恢复已获用户审核；新权威历史通过再次核验。B07-02的严格浏览器FAIL未改为PASS，以用户上述限定接受决定纯源码迁移范围。没有新增技术阻断；具备提交STEP08B审核的技术前提，不能据此自动执行上传。

## Portable、数据、依赖与下一PC

源码锁仍 `step07-fix-20261011.1`，SHA `89bbf8471108a55f2b129ab41c14735865ffbaf77df7f51a621108a225612990`。业务、测试断言、依赖版本、Schema、Legacy和Portable工具未改；本轮未重建Portable。固定Runtime ZIP SHA仍 `3ffc1c0fc14a7e461f4acc8cc8453cb73ff8d62afecfd7cc9234e6c6981f0f0e`，独立制品保存、不上传Git。

PC-B先确认用户认可的工程根及批准Commit，再读AGENTS、PROJECT_BASELINE、ARCHITECTURE、DECISIONS、TEST_STATUS、本交接；取得匹配ZIP后依次Setup、Check、TEST启停、浏览器E2E、回归和Portable验收。不能用旧现场数据库/私有配置或全局Python代替恢复；反向Git交接仍需实际审查版本与本机结果。

原历史只能作为离线回滚资料，不得合并或复制其.git至新根。需要回滚时先关闭相关会话/服务，由工程外控制脚本验证归档，将新根完整移入新的Failed目录后恢复旧根；出现新Commit或归档变化时停止另审，不覆盖、不删除、不强制重置。自动回滚路径未在本轮故意触发，NOT_TESTED。

## 停止与审核

本轮切换与新根恢复技术验证完成。当前服务已关闭；无GitHub远程、Push或新Commit。建议验收后从Codex项目中解除备份目录附加引用，但保留磁盘归档；未代用户更改项目绑定。等待用户和ChatGPT审核，不自动进入STEP08B。
