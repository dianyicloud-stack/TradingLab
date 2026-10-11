# ADR 0008：5m 复用单一 Replay Engine

选择新增 timeframe adapter、canonical Bar 和 MarketStore 分区，复用 Runtime/Repository/seek/revision。Guard 使用带时区 Bar 完成时间，先裁前缀再计算。拒绝双 Engine 与前端隐藏未来数据。日线 Contract 行为保留；5m Child 的父回退访问限制由服务端执行。
