# STEP07：13 项私人捕获测试逐项处置

CURRENT · 原跳过条件和断言未改；本轮 13 SKIPPED，不宣称原生产捕获已经复现。

权威源码及两份干净克隆缺少全部 13 个预期输入文件；只读原 TradingLab 中 13 个均存在。本轮仅核对存在性，不读取捕获正文、不复制或执行其旧算法快照。原始证据并未丢失；它们因私人生产现场信息有意排除出 Git。测试必须使用隔离账户、合成行情，不能把历史私人捕获原样导入来消除 SKIPPED。

| 原测试（ProductionBacklogTests） | 用途 | 所需原输入 / 不可替代断言 | 合法合成补充与限制 | 状态 |
|---|---|---|---|---|
| `test_consecutive_provider_failure_then_live_chain_recovers_without_false_cursor_or_trade` | 连续两次Provider失败后恢复，水位/账本无虚假成功 | 原冻结输入、前次Opinion/成功水位、比较基准；精确历史数据不可由合成替代 | 原完整回归的Fake Provider失败恢复及Owner链；可追加合成失败链 | SKIPPED / ACCEPTED历史例外 |
| `test_three_stock_live_chain_parallel_keeps_accounts_and_cursors_isolated` | 三股票并发Live链，账户与水位隔离 | 三股票同批捕获、前次结果及基准；原身份/时序需原证据 | 原Agent多股票/并发与账户测试；新增合成并发预算/Hash独立 | SKIPPED / ACCEPTED历史例外 |
| `test_two_exact_original_failures_and_original_success_control` | 精确复现两次原始预算失败及一次成功对照 | 旧evidence.py、三份未水合捕获；精确14467 token估计须原快照 | 不能等价替代原故障/数值；保留SKIPPED | SKIPPED / ACCEPTED历史例外 |
| `test_all_three_same_asof_evidence_fit_with_actual_http_guard` | 三份同as-of输入在实际HTTP RequestGuard边界内适配预算 | 三份捕获、比较基准、原HTTP请求模板及action policy | 原MockTransport/RequestGuard测试覆盖网络发送前限额；不复现原请求大小 | SKIPPED / ACCEPTED历史例外 |
| `test_formal_values_events_and_each_comparison_reference_roundtrip` | 正式值、事件与每一比较引用无损往返 | 正式行、原native SHA和证据引用拓扑 | 原无损codec；新增合成事件零/false/null/转义字段往返；原SHA关系仍需捕获 | SKIPPED / ACCEPTED历史例外 |
| `test_missing_or_wrong_historical_reference_fails_before_provider` | 缺失或错误历史比较引用在Provider之前拒绝 | 捕获中的原引用与比较基准 | 原引用校验实现及相关基础测试；可独立合成引用失配，未冒充原例 | SKIPPED / ACCEPTED历史例外 |
| `test_actual_backlog_continued_to_1501_without_success_can_recover` | 到15:01继续积压但未成功时仍能恢复 | 同一股票初始及later原捕获、前次意见身份 | 新增5000行合成积压覆盖容量；原15:01时序需原始证据 | SKIPPED / ACCEPTED历史例外 |
| `test_high_frequency_growth_from_existing_production_scale` | 以实际生产规模加密采样后仍保留所有快照 | 原生产规模捕获及元数据 | 新增5000行合成积压保留计数与极值；无法声明真实规模等价 | SKIPPED / ACCEPTED历史例外 |
| `test_summary_retains_every_referenced_time_extremum_crossing_and_quality_boundary` | 摘要保留引用时间、极值、穿越和质量边界 | 原捕获及事件邻域引用 | 新增合成摘要与原summarize结果核对；原事件邻域仍需捕获 | SKIPPED / ACCEPTED历史例外 |
| `test_auto_checks_link_to_the_same_full_validation_without_repeating_history` | AUTO校验链接指向同一完整验证而不重复历史 | later捕获的auto qualification和原validation | 原调度/证据测试部分覆盖；可合成链接拓扑，历史拓扑仍缺失 | SKIPPED / ACCEPTED历史例外 |
| `test_future_and_other_symbol_session_or_day_cannot_hide_in_compaction` | 未来数据、其他股票/Session/日期不能混入压缩 | 带比较基准的原捕获 | 原future/other-symbol基础测试；新增comparison context跨Session/跨日/未来拒绝 | SKIPPED / ACCEPTED历史例外 |
| `test_three_parallel_inputs_configuration_and_hash_are_independent` | 三并发输入各自预算、配置、Hash独立且确定 | 三原捕获 | 新增三种规模并发预算、Hash、输入不变及重复确定性测试 | SKIPPED / ACCEPTED历史例外 |
| `test_overwhelming_required_events_still_refused_not_dropped` | 必需事件超过预算时拒绝而不丢弃事件 | 原成功捕获作为模板；新构造1000项事件 | 新增纯合成1000事件超预算拒绝、source_counts完整保留 | SKIPPED / ACCEPTED历史例外 |

输入清单和存在性见 [skipped-disposition.json（原件未随候选发布，见说明）](../../RELEASE_EVIDENCE_SUMMARY.md)。原用途来自同一 HEAD 的 [test_input_budget_backlog.py](../../../tests/test_input_budget_backlog.py)。独立合成补充实际执行 7 项 PASS，脚本及原始记录保留在 `.dev/step07/synthetic_budget.py` 和 `synthetic-budget.log`。它们没有替换原测试，也不证明历史 token、原 SHA、原账本或生产压力的精确等价。

重新执行条件：在改动相关证据算法、依赖原故障结论或声称生产捕获复现之前，由数据Owner提供单独授权、来源与Hash，审查脱敏/使用边界；审查通过后在新的隔离环境运行。不可伪造原 token 数、捕获值或改写原断言。
