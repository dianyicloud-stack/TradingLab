> CURRENT · STEP07-FIX 发布候选。原文中的 STEP06/07 提交与验收是历史来源，非本候选祖先或当前测试结论。最新适用状态见 `HANDOFF_CURRENT.md`；原始现场证据仅本地保存。

# 知识来源、证据优先级与缺失范围

CURRENT · 2026-10-11，STEP06 状态补充。以下来源访问范围记录 STEP05 历史取证；STEP06 新增本地 Git 证据见 [本轮报告（历史版本，本地保留）](https://github.com/dianyicloud-stack/TradingLab/blob/7b61c5c3c443d1a6889440efdf3a640d53e376b2/STEP06_TradingLab%E6%9C%AC%E5%9C%B0Git%E5%88%9D%E5%A7%8B%E5%8C%96%E5%8F%8A%E5%AE%89%E5%85%A8%E5%AE%A1%E8%AE%A1%E6%8A%A5%E5%91%8A.md)。知识按“当前源码与锁 → 同版本实际测试 → 已审核报告 → 有边界的对话摘要 → 历史需求”交叉核查；用户当前明确范围优先。旧对话不作为运行指令，不复制原文、个人身份或私有现场。

| 来源 | 已访问范围 | 可以支持 / 不能支持 |
|---|---|---|
| 当前源码 | Shell 组合/服务、Agent/桥接、Live/History、AI Worker、Account/账本/规则、System/Telegram、DEV/Portable 控制和锁 | CURRENT 实现与引用；不能证明当前正式服务状态 |
| 当前技术文档 | ARCHITECTURE、DATA_OWNERSHIP、CONTRACTS；Agent、账户、AI、History、Windows、生命周期、DEV 等相关章节 | 技术意图与历史验收；旧标题“当前”不自动成为本轮当前 |
| STEP02/03/03-FIX/04/04-FIX 报告与证据 | 当前工程内保留版本，最新 431 回归与部署/安全结果 | HISTORICAL 实测；本轮结果单独记录，不覆盖旧日志 |
| 旧 Codex 会话“【Trading Lab V2】目录：TradingLab” | 实际 read_thread 两页 20 轮，最新到旧的范围为 STEP02 工作区切换、STEP01、便携审计/RC1、Windows入口、运行管理、AI模型、用户组合、历史结果及四模块收敛；分页仍 hasMore=true | 已返回内容经选取读取，正文和工具细节很长，未逐条审计全部工具内容；只能佐证上述阶段摘要，不宣称通读完整会话 |
| 当前迁移会话 | 用户 STEP02—05 指令、可见交付与当前用户验收声明 | 当前要求和批准状态；实际测试数字仍以保存日志为准 |
| 归档会话目录 | 查得 3 个归档条目，其中 Core 问题排查、Share 小程序/PWA 相关会话；仅目录元数据，未读取正文 | 仅证明有记录，不能支持功能或决策；目录预览可能含私人现场，未保存为公开证据 |

HISTORICAL 会话检索的限定元数据在 [conversation-access.json（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)。不向 GitHub 写旧会话逐字正文、账户名/密码、进程实例或接收目标。

## 缺失与保留策略（UNVERIFIED / HISTORICAL）

- 旧主会话更早分页、归档 Core/Share 正文、未列出的聊天/本地旧会话、ChatGPT 审核对话全文，本轮未读。缺范围如上；不宣称平台无法读取，只如实标为未读取。
- HISTORICAL：STEP05 时无 `.git`。CURRENT：STEP06 首次本地提交为 `6d655308096abc69cc3f3cb8d8df855cc170b45d`；迁移前的原作者/提交时间/精确 commit/tag/撤回差异链仍缺失，不能用本次提交或文件日期补造。
- STEP02 有意未公开 5 份生产报告和若干原始捕获，17 份技术材料经过脱敏；这些材料不自动补入本轮。来源：[STEP02报告（历史版本，本地保留）](https://github.com/dianyicloud-stack/TradingLab/blob/7b61c5c3c443d1a6889440efdf3a640d53e376b2/STEP02_TradingLab%E7%BB%9F%E4%B8%80%E6%BA%90%E7%A0%81%E6%95%B4%E5%90%88%E6%8A%A5%E5%91%8A.md)、[未可用输入清单（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)。
- 旧 Agent 文档指向 `MARKET_SOURCE_CUTOVER.md` 和旧提取输入集成文件，当前公开工程无相应完整材料；当前运行依赖以实际桥接/Agent源码和锁为准。保留旧文档原文，不编造替代报告。旧文档链接缺口不作为本轮新链接已通过的依据。
- 私人捕获依赖测试 13 项保持 SKIPPED；旧预算/生产探针/提取工具有保留源码不等于可以完整复现旧环境。未经脱敏和授权不执行历史生产探针或导入旧库。

HISTORICAL：STEP05 新知识文档来源链接与源码论断记录于 [knowledge-checks.json（原件未随候选发布，见说明）](RELEASE_EVIDENCE_SUMMARY.md)。CURRENT：STEP06 为排除生成的账户/运行状态，将三份 STEP04 合成状态捕获保留在本地、不纳入 Git；旧报告与校验索引不改写，克隆后这些历史引用不可用，具体清单见 [STEP06报告（历史版本，本地保留）](https://github.com/dianyicloud-stack/TradingLab/blob/7b61c5c3c443d1a6889440efdf3a640d53e376b2/STEP06_TradingLab%E6%9C%AC%E5%9C%B0Git%E5%88%9D%E5%A7%8B%E5%8C%96%E5%8F%8A%E5%AE%89%E5%85%A8%E5%AE%A1%E8%AE%A1%E6%8A%A5%E5%91%8A.md)。未知事项的责任节点见 [HANDOFF_CURRENT](HANDOFF_CURRENT.md)。
