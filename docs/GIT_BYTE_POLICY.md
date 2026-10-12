> CURRENT · STEP07-FIX 发布候选。原文中的 STEP06/07 提交与验收是历史来源，非本候选祖先或当前测试结论。最新适用状态见 `HANDOFF_CURRENT.md`；原始现场证据仅本地保存。

# Git 原字节与 Portable 锁策略

CURRENT · STEP06 · 2026-10-11。首次本地基线为 `6d655308096abc69cc3f3cb8d8df855cc170b45d`，分支 main，未上传 GitHub。证据见 [STEP06报告（历史版本，本地保留）](https://github.com/dianyicloud-stack/TradingLab/blob/7b61c5c3c443d1a6889440efdf3a640d53e376b2/STEP06_TradingLab%E6%9C%AC%E5%9C%B0Git%E5%88%9D%E5%A7%8B%E5%8C%96%E5%8F%8A%E5%AE%89%E5%85%A8%E5%AE%A1%E8%AE%A1%E6%8A%A5%E5%91%8A.md)。

## 原字节规则

根 `.gitattributes` 使用 `* -text -filter -ident -working-tree-encoding`。它对所有已审核文件关闭换行、内容过滤、ident和编码转换，保留现有LF、CRLF及混合内容。它没有关闭文本diff或空白检查，不将业务源码转换为LFS指针。

本机系统Git原配置为 `core.autocrlf=true`；本仓库仅本地设置 `core.autocrlf=false`、`core.safecrlf=true`。仓库属性随提交携带，本地config不随克隆携带，因此跨PC字节保护主要依赖已跟踪的`.gitattributes`。本地`core.whitespace`为默认检查项加`cr-at-eol`，识别正常CRLF，仍检查尾空格、尾空行和缩进空格后Tab。

禁止无审计的`git add .`、批量`git add --renormalize`、编辑器全目录换行转换或为迁就Git更新Portable锁。新增/修改嵌套`.gitattributes`、全局属性、`.git/info/attributes`、filter或working-tree-encoding前，必须重新检查受影响Blob和构建锁。高优先级本机覆盖可能改变行为，不能把本策略解释成任意配置下的保证。

## STEP06 实际证据

- CURRENT：首次暂存665文件，13,784,316字节；每个Git Blob均与工作文件SHA-256及字节内容相同。
- CURRENT：235业务/静态输入、11构建输入全部匹配严格锁；81个冻结文件包含在核验范围，Legacy只作静态读取。
- CURRENT：初始文件CRLF 356、LF 257、混合50、无换行2；严格246文件CRLF 81、LF 132、混合32、无换行1。全部保留原状。
- CURRENT：使用临时`core.autocrlf=true`及`core.eol=crlf`执行`git hash-object --stdin-paths`与`git cat-file --batch --filters`，665文件的入库/检出过滤输出全部保持原字节。无`-w`对象写入、无独立检出目录。
- ACCEPTED：初始`git diff --cached --check`退出2的27处问题均为既有字节，用户仅接受[登记清单](migration/step06/whitespace-review.json)。未禁用检查，后续新增改动不享有该例外。
- UNVERIFIED：本地过滤结果不等于干净clone或第二PC验收。STEP07/08仍须按获批范围验证实际检出、匹配Runtime ZIP恢复和Portable构建。

## 下一台 Windows PC

先确认获批源码Commit、独立路径及`.gitattributes`，检查有效Git属性；严格锁文件工作副本SHA须与锁及Git Blob一致。Runtime ZIP不在Git中，须经可信渠道单独取得，并匹配`dev/runtime-lock.json`。之后才按授权使用Setup-Dev、Check-Dev等入口。不要复制旧PC的`.venv`或私有配置，也不要退回全局Python/Node。

三份旧合成状态捕获仅保留在原本机，不影响运行/构建白名单；克隆不能完整复验这些旧捕获，清单见[排除记录（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)。新生成状态、Runtime和私有授权仍不得入Git。
