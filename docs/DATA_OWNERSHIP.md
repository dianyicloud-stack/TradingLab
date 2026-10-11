# 数据所有权

| Owner | Fact | Runtime / 配置 | 写权限 |
|---|---|---|---|
| Market Data Agent | Snapshot、Observation、Event、指标基准 | Session、行情采样、原生身份与删除边界 | Agent 所有者命令 |
| Live / Advisory | 不可变 Frozen Input、Opinion、Provider 请求证据 | 每股票队列、成功/消费水位、阅读位置、AI偏好 | Advisory 服务与其维护入口 |
| 数据观察 / 历史分析 | 截止日隔离输入、短期不可变历史 Opinion | live/history 工作缓存、独立任务与图表偏好 | HistoryStore / HistoricalAnalysis；不写实时或账户状态 |
| Account | 意图、订单、成交、费用、账本、批次、恢复证据 | 投影、执行模式、风控、估值 | Account Engine |
| System | 通知投递结果和必要去重身份、维护摘要 | 来源配置、发送队列、保留策略 | System 服务 |

前端和 Shell 不直接写业务库。跨 Owner 使用值型 Contract，不传数据库连接或任意路径。维护按已有所有者顺序和租约执行，保护当前任务、账户证据、指标基准、身份与水位。

退出产品的数据在确认主链无引用后删除。历史账户引用的训练判断和身份已转入 Account 的哈希校验只读证据；原账本中的 MIGRATION_SOURCE 自包含原始账户事件。不能为清理账户证据而重新导入旧运行模块。

普通日内数据按已有保留策略清理；当日意见与受引用输入保持可读，成功水位不归零。通知清理不遗忘已确认投递边界。

历史手动分析例外：按上海本地创建/完成日的轻量TTL，仅当天可复看，次日后台清理（含周末，启动补查）。result_index引用原jobs正文；显示投影不覆盖Opinion。该Owner没有实时、账户、通知写能力，历史TTL不改变它们的保留策略。

.env、来源凭据和所有 Agent 数据根不得进入公开诊断。legacy/ 禁止写入、导入或执行。

Account组合控制数据库保存名称、创建幂等、执行绑定和最小删除标记；Account独有账本保存风险暂停及修订。删除先解除绑定并禁止写入，再清除该账户独有文件，不删除公共Opinion/行情/通知。原实时账户迁移只登记元数据，不改原账本。

## System运行意图与进程描述（计划16）

System拥有data/system/runtime-control.json（意图、版本、首次迁移、启用时间、自启模式）及runtime/supervisor.json（敏感本机控制凭据，不向公开API返回）。Web/Agent分别发布自身身份及控制描述。Supervisor不连接业务数据库；活动工作、保存结果和未知结果恢复仍经Live/History/通知/Agent Owner。不得用运行控制改账户授权。
