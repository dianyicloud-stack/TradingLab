# STEP07-FIX 候选交接

CURRENT · 仅独立发布候选，等待审核。

Domain 为发布隐私和浏览器验收；数据 Owner、Fact/Runtime、Contract 不变；写权限仅隔离候选和测试生成物。冻结协议与 81 Legacy 原字节不变。只经用户批准脱敏两个锁定文档及更新对应 Hash、精确历史差异断言，不修改业务实现。

候选通过独立新 Git 初始化记录实际创建日期，不继承旧历史。当前 Commit 用 Git 读取；原版本关系、具体变更及当前验收由主工程独立 STEP07-FIX 报告记录，不制造 Commit 自引用。

计划验证：完整 Blob 隐私与字节、235/11/81 完整性、真实检出、Setup/Check、431 回归、冻结与 Portable 重建/专项。此处不预填 PASS；结果待独立报告。所有测试须 TEST/Fake，固定运行环境，本工程 TEMP，禁止真实 Provider/通知。

遗留门禁、Portable 兼容性、缺失原证据、下一 PC 顺序和审核范围见 [当前交接](../HANDOFF_CURRENT.md)、[证据说明](../RELEASE_EVIDENCE_SUMMARY.md)、[开发环境](../../dev/README.md)。阶段推进仍须用户与 ChatGPT 决定。
