# Frozen Baselines · Foundation v0.1

## 冻结范围

最终冻结清单覆盖 legacy 全部 81 个文件，包含 V2A、V2B、Account、V2B_BAK 和现有测试/缓存。
本次最终冻结只授权替换 V2A.1.2.1 的错误参考副本；其余 Legacy 内容未移动、修改、执行或导入。

初始采集时间（UTC）：`2026-09-05T06:05:48.2263652Z`；Source Audit 与最终冻结日期：`2026-09-05`。
完整逐文件最终清单和权威状态见 [frozen_baselines.json](frozen_baselines.json)。

**复制时间无法从现有资料独立确认。** 下表列出文件系统 CreationTimeUtc 作为观测值，不能冒充真实复制时间或上游版本发布时间。

## V2A 最终冻结结果

| 版本 | SHA256 | Status | 说明 |
|---|---|---|---|
| V2A.1.2.1 | `5fb58532d16628694239459c059d42fa2c7d889622a9893983ba2671ff412df6` | `FROZEN` | 使用旧项目中与历史权威 Hash 一致的源文件，替换含外部注入内容的错误副本 |
| V2A.1.2.2 | `fd155f387747551a603b21ac0f54e7618ef3e47f95bf5ab0b2bc13043441f2ae` | `FINAL_ACCEPTED_FROZEN` | ACK 恢复、原子写入等验收修补后的最终活动版本；Manual Closed Loop 已通过 |
| V2A.1.2.2 pre-fix | `c5921ca8a62490d4d8ec70e903b4ea983d1d185341743dad2189113e5dba72d2` | `PRE_FIX_HISTORICAL_SNAPSHOT` | 验收修补前备份，仅作历史参考，不参与最终 Frozen Baseline 校验 |

## Source Audit 结论

- V2A.1.2.1 权威源：`LOCAL_HISTORICAL_SOURCE/量价查询_V2A.1.2.1_每日状态重置_放弃即删除.html`。
  旧 Trading Lab 副本多出 1,297 字节 Kaspersky 外部脚本/样式注入；原 V2A 内容其余部分一致。
  最终副本已由权威源做字节级替换，替换后 Hash 严格等于历史权威值。
- V2A.1.2.2 最终权威源：`LOCAL_HISTORICAL_SOURCE/量价查询_V2A.1.2.2_Decision_ACK导入版.html`。
  它与 Trading Lab copy 字节完全一致，属于后续验收修补后的最终活动版本。
- c5921ca8… 的实际来源是 `LOCAL_HISTORICAL_SOURCE/量价查询_V2A.1.2.2_Decision_ACK导入版_验收修补前备份_20260904.html`。
  该 Hash 有真实文件证据，历史记录本身并非错误；其语义是 pre-fix snapshot，而非最终接受版本。
- Source Audit 说明了“复制后未变化”不能证明“复制来源正确”。最终 Checker 同时校验完整文件清单和两份权威 V2A Hash。

## 主要文件、观测创建时间与用途

| 文件 | SHA256 | CreationTimeUtc（观测，非确认复制时间） | 用途 |
|---|---|---|---|
| `legacy/account_engine/account.py` | `58735261be0908d52a65f48defb3796de5cea33dfa94e2fa0afb3e19d6fc47bf` | 2026-09-05T05:51:36.3654068Z | 独立影子账户基线；不迁移账户运行数据 |
| `legacy/account_engine/config.json` | `ae46efe7d6f64ee42002fd647cf7bc3b3327034c625cf2acc44afbaa13537b91` | 2026-09-05T05:51:36.3719930Z | 独立影子账户基线；不迁移账户运行数据 |
| `legacy/account_engine/engine.py` | `56b181b3a4f4cd34269a6ab1f1eb4a47a7933cec3cc37f10c3882bb259d4f6e9` | 2026-09-05T05:51:36.3719930Z | 独立影子账户基线；不迁移账户运行数据 |
| `legacy/account_engine/README.md` | `b1cb0c40d7456aa971a43c083426d95cb54663abcf3d386fe189cf629ffd994c` | 2026-09-05T05:51:36.3862591Z | 独立影子账户基线；不迁移账户运行数据 |
| `legacy/account_engine/reporting.py` | `8eebcf2b592b9b918868c0fa8b35b3f1f5a303fe79ae9cde1247398732bb9040` | 2026-09-05T05:51:36.3862591Z | 独立影子账户基线；不迁移账户运行数据 |
| `legacy/V2A/量价查询_V2A.1.2.1_每日状态重置_放弃即删除(4).html` | `5fb58532d16628694239459c059d42fa2c7d889622a9893983ba2671ff412df6` | 2026-09-05T05:38:08.2087757Z | `FROZEN` · Source Audit 后的权威副本 |
| `legacy/V2A/量价查询_V2A.1.2.2_Decision_ACK导入版.html` | `fd155f387747551a603b21ac0f54e7618ef3e47f95bf5ab0b2bc13043441f2ae` | 2026-09-05T05:35:37.8860515Z | `FINAL_ACCEPTED_FROZEN` · 最终 LIVE 参考 |
| `legacy/V2B/.pytest_cache/README.md` | `73fd6fccdd802c419a6b2d983d6c3173b7da97558ac4b589edec2dfe443db9ad` | 2026-09-01T13:25:04.0745433Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/config.yaml` | `ee39a20473011e8c2b7c2aaa74f889d6cb6c6b396bc673ddeae3460f5fa70dbd` | 2026-09-01T13:17:47.9669474Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/__init__.py` | `0de9911221e7e6e747eff4d4556de96f5dbc0959c4b4161a2b555f36fc6afdfe` | 2026-09-01T13:19:37.8179698Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/ack_receipt_manager.py` | `4653563cb6e3fba387fcbcf2c23e3b557a44e92d38b4c395167f88c264f3c6ec` | 2026-09-04T14:32:36.8622484Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/action_policy.py` | `f667115eb4cacd6871d4f5e4cc78a15d986e521264b2a257a429587600752ecb` | 2026-09-03T14:04:07.5517710Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/config_manager.py` | `7990e895926f9f317619d0467eb72ce44f3e8449909cc270d023cf801b8d7d51` | 2026-09-01T13:19:37.8219691Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/decision_manager.py` | `901f2dfa38903255bb391771adf7b7f06f5ebcd4d7fa50d818ac4ccd34e616c2` | 2026-09-01T13:19:37.8229700Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/decision_store.py` | `98c3b12a31f9c688723fc5231dab61f3e89d19ac0dbc3a79a54fff0ed3a9b773` | 2026-09-01T13:21:51.9882304Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/errors.py` | `7898428e165ceeb737dbc7072ffc5b690230c358099773eac9bca7874f21ded3` | 2026-09-01T13:19:37.8179698Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/event_manager.py` | `f50ed4ee20ba15451349bd00ae4c2c920ffb7c5537ed85528ddfd5b0500411cc` | 2026-09-01T13:19:37.8219691Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/job_manager.py` | `30b02e526c77a8ee14a3a19f5ec4abb841d7a10796dce2d24fda7dd46ae31aef` | 2026-09-01T13:19:37.8229700Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/models.py` | `911f9be9d751af4be2495c31673c9c979685daf0c29227b5b575b38f2822ac69` | 2026-09-01T13:19:37.8189710Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/request_archive.py` | `58492e350515e2757460d03594697c27ae021f26dfbc80dd1477f24db0816b89` | 2026-09-04T12:20:02.3058507Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/request_fingerprint.py` | `2e3734138e6f7ab7f0ba7106bbc2d11773bbaaee13c929f30fffcf497c7234f4` | 2026-09-03T14:26:17.5916078Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/review_manager.py` | `0ef569ac01ad0c98e42479250a9b18369ec26178dfdddb13f99c34f1a68fa194` | 2026-09-04T12:22:19.7225440Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/service.py` | `8ccbb2c11213ce9e68ad4e0a35d7fad61468237bd670da4e7805238ad1cd8f88` | 2026-09-01T13:21:51.9892315Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/storage.py` | `bc9b3860da74290fe491e293c481cc68d5f5ba4cee1ff84629ca2e67ec15024b` | 2026-09-01T13:19:37.8189710Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/coordinator/usage_manager.py` | `4c2f6421b6b821edb96657c4c63356e79582226af0e882c9ab63f8241a1c0123` | 2026-09-01T13:19:37.8229700Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/providers/__init__.py` | `3f60944371ba129ba94654967bf55d0df43922d12e07f2d171894be552427861` | 2026-09-01T13:21:51.9584772Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/providers/base.py` | `891d9ed555ede4dc34300e4610fba6cbba734fe3f93bf375a219f0c66a5d2866` | 2026-09-01T13:21:51.9626250Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/providers/deepseek_provider.py` | `62dc7f3809c177283270e0e45edf1a5ce8133a9abf20bbce6850a9c91340b6e1` | 2026-09-01T14:43:01.8526806Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/providers/openai_provider.py` | `923ce0c8e073678097ccef53a6964cdbd2259d04d7fe3f95fcb5d62abd203e8b` | 2026-09-01T13:21:51.9626250Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/README.md` | `0cc30faf47b43e1681fbedf0b2b59c18bef2956cc6b27b9989b6baf1d6e1e658` | 2026-09-01T13:26:24.2782448Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/requirements.txt` | `da9f862d2086d77fde51c5aff38a17324fd6bdd9c52dd1f5e4529605a6b0380b` | 2026-09-01T13:17:47.9943312Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/schemas/ack_receipt.schema.json` | `53b44ba0ae63e37e838637241e6b52d962c196192bdddfeac4b38fc933ee6b39` | 2026-09-04T14:32:36.8622484Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/schemas/decision.schema.json` | `bb7577ddf55ddeb7907a8112ec61360526fba77a27a23078decb6dd369f1cfb2` | 2026-09-01T13:17:47.9959012Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/schemas/event_handoff.schema.json` | `f0e61a61396aa199d33178130920081709ed9e9e962d42a85a2143838a16336d` | 2026-09-01T13:17:47.9953355Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/tests/tmp_ack_consume_state/README.md` | `8903a82f3457c97a05624740b58c026965265e72490e72bb97bb967482a1c41a` | 2026-09-05T01:41:18.3225550Z | 人工决策闭环 / 冻结规则与协议参考 |
| `legacy/V2B/v2b_coordinator.py` | `6a766e08dce9041b2f415afc9d0324208638d36111c84c603d7b4d88f9d0b580` | 2026-09-01T13:21:51.9892315Z | 人工决策闭环 / 冻结规则与协议参考 |

## 校验方式与含义

`python trading_lab.py --verify-baselines` 或 `.\start_trading_lab.ps1 -VerifyBaselines`。

- `unchanged=true`：当前完整文件集合和 SHA256 与本次最终冻结清单相同；也检查新增/丢失文件。
- `frozen_baselines=PASS`：V2A.1.2.1 和 V2A.1.2.2 都与各自权威 Hash 一致。
- `authoritative_checks` 分别给出两个版本的 expected、actual、冻结状态和 PASS/FAIL。
- 文件变化、权威 Hash 差异或清单内部冲突：报告 CHANGED/ADDED/MISSING/MISMATCH/MANIFEST_CONFLICT，CLI 返回 1，Health ERROR。
- 校验器只有读取行为，不会重写 manifest、修复 HTML、运行 legacy 或自动接入旧系统。
- 此清单是本地完整性基线，不是数字签名；若清单与文件同时被人工篡改，需要外部备份发现。
- V2B README 的 A+B.2 只是声明版本；精确身份由逐文件 hash 确定，不能推断未知上游 commit。

最终冻结后复核：81 个文件均匹配清单，两份 V2A 权威基线均为 PASS；详见 VALIDATION.md。
