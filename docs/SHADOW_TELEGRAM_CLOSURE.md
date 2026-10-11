# 自动影子交易演练与 Telegram 通知（2026-09-23）

> 最新用户授权：自动分析和手动“立即分析”（含明确确认的重新分析）成功后均推送。手动功能有独立升级边界，不补发升级前的意见。18 项通知测试通过，正式加载与保护核验见 `telegram_manual_deployment.json`。下文初次部署的实发消息与演练记录保留。

本轮不改变 Agent 来源、Provider、交易规则、账户权限或清理框架。正式账户仍为 ADVISORY_ONLY，Listener STOPPED。
[STEP 02 脱敏：已移除生产账户、个人通知目标或运行实例细节。]
同时其账户结果记录 MARKET_EVIDENCE_INCOMPLETE。这些是没有成交的实际原因，未发现须修改的 Account Engine 执行缺陷。

## 隔离演练

`tests/test_shadow_drill.py` 以少量明确合成事实、SimulationLiveFactSource 可见时间守卫、Fake AI 和模拟时钟，
调用真实 AdvisoryService ingestion/auto debounce/请求任务/Opinion 保存/PortfolioService/AccountEngine/ledger。
独立 TEST 账户使用现有 policy；只把该隔离账户设为 AUTO_SHADOW_EXECUTION。没有向账本直接插入持仓、手动成交或改变正式账户。
北交所规则沿用当前实现：最低 100 股、后续 1 股递增、T+1、价格步长 0.01，以及现有滑点和费用。
订单及成交的模拟时间不早于意见可用时间；报价在模拟时点已经可见。账本写入时钟仅在隔离测试中注入。

|场景|实际结果|现金|持仓|
|---|---|---:|---:|
|25% 合格建仓|自动成交 4995 股，10.01 元；费用 15.50|149984.55|4995|
|重复窗口/同一建议|同一执行身份，仍只有 1 次成交|149984.55|4995|
|证据不足|LIMITED_EVIDENCE，未调用 Fake AI、未形成成交|200000|0|
|资金不足（100 元本金）|MINIMUM_LOT，目标数量达不到最小交易单位|100|0|
|仅建议|WAITING_HUMAN_CONFIRMATION，未成交|200000|0|
|当天退出|T1_LOCK，递延，未成交|149984.55|4995|
|下一交易日退出|自动卖出 4995 股，10.99 元；费用 44.47|204835.13|0|
|重建及重复退出|账本与投影一致；重复建议不重复成交|204835.13|0|

数值证据在 `shadow_drill_results.json`。演练的运行目录测试结束直接删除。

## 所有者与触发 Contract

Account 继续独占账本；Live 拥有分析请求和成功水位，Advisory Opinion 保持不可变。
System 仅拥有 `data/system/notifications/telegram.db` 的发送状态，不写账户、Opinion 或分析游标。
组合根注入 Live 的 `notification_boundary()`、`notification_completions(after,limit)` 和轻量 `success_observer`。
回调发生于 Opinion append、成功游标提交、请求状态 COMPLETED 之后，只唤醒后台，不等待网络。
每批至多查询 100 个请求元信息；通过 Live 所有者读取对应成功保存的 Opinion，不读取浏览器或当前阅读版本。
安装边界使用持久化 AUTOINCREMENT 请求序号，旧历史不补发。运行/排队请求暂不越过，避免并发任务乱序完成时漏项。

仅正式 USER 命名空间、LIVE 模式、AUTO_EVENT / MANUAL / MANUAL_REANALYSIS、COMPLETED、有效且当日的 Opinion 合格。
TEST/Simulation、失败、无新数据、运行中、已过期结果均不发送。
后台发送不依赖浏览器，失败不改变分析/账户状态、游标，不重新调用 AI。

## 正文映射

- 本轮结论：Opinion `name` + 去交易所前缀的 `symbol`，中文 `action`，`game_state` 文本或 `game_state.summary`；缺失则使用 `current_state`。
- 核心依据：`core_conflict`。
- 接下来观察：`next_observation_focus` 字符串，或 `target/watch_for/meaning` 结构化条目。

取本次保存的原值，沿用 Live 的中文判断码映射；保留价格、单位、否定和条件，缺字段写“本轮未提供”。
没有账户、模型、置信度、耗时、事件计数等第四模块，没有额外 AI 摘要调用。

## 投递与生命周期

唯一键：namespace + Opinion ID + chat_id + TELEGRAM。不同轮次正文相同也发送。
每个私聊串行、请求间隔至少 1.1 秒。按段落优先拆分，按 UTF-16 单位保守控制不超过 4096；不丢弃字符。
逐段记录确认的 message_id；只有 Telegram ok=true 且返回有效 message_id 才算该段成功。
429 遵守 retry_after，每段最多 3 次尝试。401/403/参数错误停止当前配置继续投递；修正 Token/目标/通知代理并重启后解除配置阻断。
超时、网络断开、无法确定响应或发送中崩溃标记 UNKNOWN，不自动重发；已确认段仍记录，未确认的剩余段不假称送达。
网络故障下不承诺绝对恰好一次。

待发送正文至多 1000 份；达到上限时恢复登记水位暂缓。跨日待发送正文过期并清除，终态正文即时清除。
投递状态保留 7 日，之后删除；小型安装/恢复水位持续保留，防止每日清理后重发。关闭通知也会清除过期正文。
没有新增备份、消息平台或 Telegram 双向命令。

## 本机配置与实际生效

[STEP 02 脱敏：本节运行现场与生产捕获细节未纳入统一源码。]

# 每次显式执行只发一条测试，非交易建议；不调用 AI 或写正式 Opinion
.\.venv\Scripts\python.exe .\tools\test_telegram_push.py --send
# 修改 .env 后真正换一个 Web 实例加载配置，不是连接旧进程
.\tools\restart_web.ps1
```

重启脚本核对实际监听进程及项目/数据根身份，暂时停止原先运行的监听并等待所有任务安全结束，恢复原监听状态。
任务未结束则不杀进程并恢复监听。只重启 Web，核对 Agent PID 不变；没有修改账户/AI设置。
本轮实际测试消息确认送达 message_id=9，仅 1 条。不是正式 AUTO Opinion，没有污染意见或账户记录。
真实 AUTO 推送需后续自然产生新的成功意见；本轮没有为了验收开启监听或调用真实 AI。
测试和部署哈希证据见 `telegram_deployment.json`，临时数据已清理。

## 修改与定向验收

新增：`adapters/telegram.py`、`contracts/live/notification.py`、`app/system/notifications.py`、
`tools/test_telegram_push.py`、`tools/restart_web.ps1`、`tests/test_telegram_notifications.py`、`tests/test_shadow_drill.py`。
接线与显示：`engines/live/advisory.py`、`engines/live/advisory_repository.py`、`app/shell/bootstrap.py`、
`app/live/router.py`（加载哈希）、`app/system/module.py`、`app/system/static/system-status.js`。
配置和说明：`.env`（保留已有 Token）、`.env.example`（空 Token）、`docs/CONTRACTS.md` 与本说明。
Account Engine、Provider、Agent、Frozen Legacy 和交易策略没有代码修改。

定向用例共 122 个：通知 16、账户账本 53、闭环演练 5、既有 AI/Agent 自动链 46、Foundation HTTP 2。
首次 Fake HTTP 测试的 mock 类型及多股完成顺序假设修正后，相关重测通过；没有放宽业务断言。
最后正文过期处理仅重测 4 个受影响用例，没有重跑全量回归或长测。System 脚本语法检查通过。
Legacy 81 个文件 unchanged=true、changes=[]，两份权威基线 PASS。13 份账户账本/投影、配置、成功水位与任务记录部署前后指纹一致。
[STEP 02 脱敏：已移除生产账户、个人通知目标或运行实例细节。]
Live/数据观察/System/Account HTTP 均正常，Listener 保持 STOPPED。

Telegram sendMessage 的返回和长度约束依据：[官方 Bot API](https://core.telegram.org/bots/api#sendmessage)。
