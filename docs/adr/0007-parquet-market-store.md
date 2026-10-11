# ADR 0007: Parquet Canonical Market Store

Accepted · 2026-09-05。

使用 pyarrow（不引入 pandas），固定 daily_v1 schema；按 symbol/year 分区。Raw JSON 独立在 market/raw。批次验证先于写入，年度临时文件原子替换。Session 创建时保存内容寻址不可变 Parquet 快照，读取时核对 SHA256。

年度分区供后续共享 Market 使用；Session 快照保证未来缓存刷新不改变已创建回放。跨年更新不是全局事务，失败拒绝 Session 创建并由重试完成。额外快照占用空间可接受；本轮不实现自动清理以免破坏审计重现。
