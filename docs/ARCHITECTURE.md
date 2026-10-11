# Trading Lab 当前架构

正式产品仅四个一级模块，依次为 Live、数据观察、Account、System。

Market Data Agent 是唯一正式行情源。独立 Agent 采集 Snapshot / Observation / Event；Web 经 Agent Contract 读取，不跨域连接其数据库。Live 按股票和 Session 构造冻结输入，保存不可变 Opinion，成功提交后分别交给 Account 和 Telegram 通知队列。

Account 拥有 PortfolioIntent、执行策略、资金、批次、成交、费用、账本与重建。用户组合账户显式创建和命名；Live使用后台持久执行绑定，与Account查看选择分离。退役历史账户隔离保留必要证据，不提供产品选择或读取入口，旧来源不再是运行依赖。

System 拥有来源连接、配置、通知和维护。组合入口是 app/shell/bootstrap.py；各前端只调用 API。Provider 代码归 adapters/ai，配置为项目根 config/ai.yaml 和绝对项目根 .env。不执行 frozen Legacy。

Learning、Research、独立 Decisions、Replay / Simulation 产品以及 Formal Handoff / ACK 执行接口已删除，旧 URL 返回 404。模拟时钟与事实仅在 tests/support，用于测试实际 AI/Account Engine；不注册产品或后台会话。

数据根与程序根分离：Agent 根从来源配置加载。Live Opinion 存储位于 data/live/advisory，运行水位位于 data/runtime/live/advisory，账户位于 data/account/unified，通知位于 data/system/notifications。不可变数据、成功水位、删除边界、账户设置在产品收敛中保留。

legacy/ 是只读冻结参考，81 文件基线单独验证。Agent 的必要历史身份/已处理水位字段用于连续恢复，并不提供旧协议执行能力。原生行情/指标计算函数保持审计版本的函数体。

历史收盘观察归数据观察 / Live：独立 History Bars Adapter → History Engine → HISTORY_EOD 手动任务。Engine 截止过滤、日/周/月聚合和同进度量能共用 JSON API；历史任务没有 Account、Telegram、实时 Event 或成功水位写能力，不新增产品模块。工作缓存归 HistoryStore；历史结果按上海本地创建/完成日保存，当日列表和去重索引引用原Opinion，不复制正文。历史专属后台TTL在次日和启动时补清理，不依赖实时交易日维护就绪，也不改变实时数据主保留规则。

## 计划16：Windows运行管理（2026-09-26）

OS任务仅启动独立System Supervisor。管理模式的Web/Agent启动权集中于app/system/runtime_control.py；Shell仅组合Owner生命周期合同。Listener意图持久化，实际循环和市场/资格判断仍属Live。Web-only为开发模式。详见RUNTIME_16_WINDOWS.md。
