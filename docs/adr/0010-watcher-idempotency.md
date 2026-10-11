# ADR 0010：持久化去重与 Repository 边界

队列 key 使用 kind + handoff/receipt ID + tracking session 集合；另存内容 SHA256。重复同内容不入队，身份相同但内容变更保留 FROZEN_INPUT_CHANGED。已完成任务重启不重跑；RUNNING 中断变 FAILED，人工 retry 明确重新分析。V2B 自身 fingerprint 幂等为最后防线。

SQLiteQueueRepository migration v1 隔离 SQL；LiveLoop 只调用 QueueRepository。owner_user_id/created_by 预留而不实现 Auth。Watch Loop 串行处理，多 Provider 调用不阻塞状态快照读取；停止等待在途调用结束，不丢任务。覆盖式上游文件在发现前被替换仍可能丢失，当前协议无法解决。
