# ADR 0005: Server-side Future Guard

Accepted · 2026-09-05。

所有 derived 计算先经过 DailyAdapter.guarded，cutoff 使用 Foundation aware datetime；日线 15:00 +08:00 可用。API 只调用 Engine view，绝不暴露完整快照。Raw cache 可以包含未来，浏览器不能。

服务器过滤后再计算 MA / rolling high-low / path hash，再截取 context_bars。测试在未来注入极端价格，当前 Facts / MA / hash 必须不变；实际 HTTP JSON 同样检查最大日期。市场提供未复权日线，避免未来复权因子影响历史。
