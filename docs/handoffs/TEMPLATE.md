# YYYYMMDD_任务名_交接报告

CURRENT · 日期 / 实际工程根 / 作者角色 / 等待用户与 ChatGPT 审核。

## 目标、范围与实际变更

记录六问（Domain、Owner、Fact/Runtime、写权限、Contract、冻结边界）、任务目标、逐文件实际修改及原因、未修改的受保护范围。源码版本写实际 Commit 或锁 SHA；不存在 Git 时明确 NOT_INITIALIZED，不能写“干净工作树”。

## 验证与证据

每项写实际命令、解释器、cwd、隔离数据/网络、退出码、PASS/FAIL/ERROR/SKIPPED 数量和证据链接。历史结果标 HISTORICAL；未运行标 UNVERIFIED / NOT_TESTED。记录敏感扫描范围、锁核验、正式目录保护和残留进程检查。

## 遗留事项与阶段门禁

| 编号 | 分类 BLOCKER / DEFER / ACCEPTED | 问题与状态 | 责任步骤 / 角色 | 最迟节点 / 关闭证据 |
|---|---|---|---|---|
| 待填写 | DEFER | 描述 | 明确后续步骤和负责人 | 明确期限或触发节点 |

不使用含糊“以后处理”。BLOCKER 只允许在关闭后推进受影响阶段。ACCEPTED 说明限制、接受依据和复核触发条件。更新 HANDOFF_CURRENT，旧交接不覆盖。

## Portable、数据、依赖与下一 PC

写白名单/锁/构建兼容性、历史锁保护、数据/Schema/依赖是否变更、真实分支和 Commit（如存在）、本机环境版本及 NOT_TESTED、下一台 PC 必读文档和安全执行顺序。知识接手演练与物理跨 PC 验收分开。

## 停止与审核

明确已完成与未授权步骤、是否执行 Git/上传、是否具备提交下一阶段审核的条件。Codex 不代替用户/ChatGPT 批准推进。
