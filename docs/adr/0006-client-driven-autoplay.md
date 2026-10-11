# ADR 0006: Client-driven Auto Play

Accepted · 2026-09-05。

浏览器 setTimeout 在上一请求完成后按 1/3/5 秒触发 NEXT。Server 是唯一 cursor 所有者，每次 mutation 携带 revision，事务冲突返回409。Pause / pagehide 停止 timer，无后台 scheduler。刷新恢复服务端 Session 后明确暂停；浏览器关闭时已发出请求可能完成一次。

好处是没有隐藏运行任务。局限是客户端节拍受网络/标签可见性影响，暂停不会取消已经提交的事务。
