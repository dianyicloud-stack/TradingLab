# ADR 0004: Replay Engine + Timeframe Adapter

Accepted · 2026-09-05。

复用 Foundation Session，增加 Runtime envelope。Engine 拥有生命周期、游标和统一逐 Bar apply；Timeframe Adapter 拥有可用时刻、时间轴与确定性 Facts。本轮仅 DAILY，INTRADAY_5M 明确报未实现。Session 固定数据快照；SQLite revision 事务解决重复推进。

向后跳转从范围首 Bar 重建，RESET 至初始可见日。以可见 Facts 累积 path_hash 支持后续依赖路径的状态，避免直接改游标绕过状态变化。暂不引入事件总线或复杂 ledger。
