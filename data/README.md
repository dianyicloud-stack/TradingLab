# Domain-owned Storage

目录布局及写入权限以 `docs/DATA_OWNERSHIP.md` 为准。启动会创建缺失目录。
Market 当前为空；仅 `learning/learning.db` 初始化。没有导入或迁移旧运行数据。
Account 的 `live/` 与 `replay/` 是物理隔离辅助目录；两个账户 DB 仅预留路径。
运行数据不纳入版本控制，Learning 事实应独立备份，不能当可丢弃缓存。
