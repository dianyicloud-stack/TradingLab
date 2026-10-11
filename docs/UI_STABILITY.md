# Live / 数据观察 / System 交互稳定性修正

本轮只改读取、投影、显示、提示和显示偏好；不切换数据源，不启动采集/AI/账户，不修改 Legacy 协议或原行情公式。

## 现场与根因

[STEP 02 脱敏：已移除生产账户、个人通知目标或运行实例细节。]

已证实：

- 单股折叠先等待 PUT 和整个 refresh；全部折叠逐股串行等待。现改为本地立即更新，后台逐股有序保存，最后操作获胜。
- Live 每轮创建完整卡片，再比较签名；行情/意见变更导致节点替换。现保留卡片、控件、details；只更新显示区，正在阅读的意见留在原版本，用户明确查看新意见后才确认该版本。
- 数据观察原 render 每2.5秒清空表格和SVG。现按 Observation identity/revision 维护行，保留表内滚动与SVG实例；仅数据变更更新图形。
- System page 和 health 各执行一次全量 snapshot；snapshot 又重复运行 Baseline 和 Live 多组件聚合。正式 /system 基线7.27–7.44秒，/api/health 3.53–3.87秒。现在普通GET读取已缓存结果，完整检查由显式后台诊断命令执行；组件表/Workspace启动证据仍保留。
- 数据观察完整响应296,784字节，其中包含重复的 session.rows、协议事实；display 查询移除重复内容，revision未变时只返回状态。Live display查询省略原始trigger证据，意见ID相同时不重复传正文。完整审计API不删字段。

未证实：持续数据库锁等待、Agent采样等待、持续长任务、图表规模需要虚拟滚动。本轮没有为了这些假设更换框架或引入缓存服务。

## 显示与接口边界

- 普通 Live：紧凑股票摘要、意见截至、未读、账户仓位/未知、立即分析；展开为当前判断、变化、核心矛盾、观察条件、账户结果。完整博弈/历史再折叠。
- 模式 / 来源 / Session 身份隔离缓存。后台响应修订号、配置命令失效标记防旧响应覆盖。表单节点保留，原生折叠不重复切换。退出页面清理定时器与 BroadcastChannel。
- 数据观察也复用后台最近成功读模型，位于 `data/runtime/live/observation_read_model/latest.json`；只缓存观察/事件展示投影，不重复存全部Snapshot、Session.rows或协议正文。页面断线保留带时间的上次成功内容，来源代际不符拒绝恢复；未恢复时不允许以陈旧界面发跟踪命令。
- GET只读；显示偏好和已读是独立命令。轮询/刷新不调用AI、Formal确认或账户记账。
- UI不在轮询时重排现有股票；明确置顶可移动。未读快捷定位只在用户点击时滚动。
- 历史意见原文不变。已知术语仅做词边界映射，数字/否定词/条件不变；未来Prompt要求中文正文，并明确首轮不等于证据不足。
- `GET /api/system/summary` 与 `/api/health` 读取检查缓存；`POST /api/system/diagnostics` 启动可合并的后台检查。持久化路径是System-owned `data/runtime/system/last-health.json`，普通GET不写它。首次深检未执行明确UNKNOWN。
- System高级审计可查询原始意见/状态，Formal审计继续在Decisions，执行事实继续在Account。

字段、时间、板块、单位与真实缺口见 [字段映射](UI_STABILITY_FIELD_MAP.md)。测试与最终实测记录见 `artifacts/ui_stability/`。

## 回退

本轮修改前代码逐文件保存在 `artifacts/ui_stability/before/code/`。只对本轮修改清单内的文件恢复；不得批量覆盖后续工作。不恢复/覆盖正式市场数据库、V2A Workspace、Opinion、账户账本或来源配置。
该备份范围仅含 app/adapters/bridges/engines/contracts/shared。`trading_lab.py` 本轮仅增加 `start_observation_model` 判断与调用两行，回退时只移除这两行；不要用更早的 market_cutover 整文件覆盖，否则会撤销已验收的来源配置功能。新增 `app/system/static/system-status.js` 在恢复引用方后不再加载，可保留。测试工具和文档不影响运行。
需回退Web时先确认无执行中命令/AI，再只重启Web；独立Agent不重启、不切源。市场桥接时间修正回退会重新暴露旧时间显示问题。

## 历史保护记录

[STEP 02 脱敏：本节运行现场与生产捕获细节未纳入统一源码。]

