# Telegram 本地接收目标授权

公开源码没有默认接收目标。现有通知触发、去重、重试、未知结果处理和账户隔离规则不变。

- 发送配置继续使用项目根 `.env` 及既有环境变量加载方式：`TELEGRAM_NOTIFICATIONS_ENABLED`、`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`。
- 本机操作者的授权只从固定路径 `.env.telegram` 的 `TELEGRAM_ALLOWED_CHAT_ID` 读取，复用 python-dotenv；不做环境变量插值，不允许环境变量覆盖授权。
- 仅当启用、Token 合法、授权为单个正整数私聊 ID、发送目标与授权完全相同时才允许发送。缺失、空白、格式错误、未授权目标均拒绝。
- `.env` 中的同名授权字段不生效。Web/API 没有修改授权或发送目标的接口；状态 API 只给出 `recipient_authorized`，不返回目标或 Token。
- DEV、TEST 及其他非 USER namespace 在读取私有文件前禁用；即使误改 enabled 标记也不能绕过 namespace 检查。

只提交 `.env.example` 与 `.env.telegram.example` 两个空模板。真实文件必须留在本机并限制 Windows 文件访问权限；`.gitignore` 排除 `.env` / `.env.telegram`，Portable 构建白名单也不包含它们。不要把有值文件复制到测试副本、构建包、文档、日志或审查证据。

首次配置时由本机操作者从空模板建立私有文件、审查唯一接收目标，并使用受保护渠道设置 Token。模板不会自动启用通知。本次迁移只把已有授权值转入私有文件，没有设置 Token 或启用标记，也没有发送真实消息。

出站队列保留原 namespace/chat_id；只有与当前授权发送目标一致的待发记录才会投递，旧目标消息不会重定向到新目标。

改授权后须重启相关 USER 服务重新加载；不要通过修改代码常量、放开任意目标或修改已封印的候选包来绕过配置。正式环境迁移、通知实发及队列跨目标迁移均需另行审批和验证。
