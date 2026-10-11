# Trading Lab

数据观察 → AI辅助判断 → 风控与影子账户。正式导航：Live、数据观察、Account、System。

日常双击桌面的 **TradingLab 启动 / TradingLab 停止 / TradingLab 状态**。项目内对应入口位于 `tools/windows/TradingLab_Start.cmd`、`TradingLab_Stop.cmd`、`TradingLab_Status.cmd`，全部委托 `tools/runtime_control.py`。默认网页为 http://127.0.0.1:8765/live。Windows 登录自动启动已关闭；保留的计划任务可通过 `runtime_control.py install-startup` 恢复。

启动会等待服务就绪，同一个 Web 实例只自动打开一次网页；关闭浏览器不停止后台。停止会等待任务收尾，停止 Web 与 Agent，按现有合同保留轻量 Supervisor 待命；监听的长期设置不变。状态窗口保留供阅读。详见 `docs/WINDOWS_ENTRIES.md`。

`trading_lab.py` 保留为 Supervisor 内部兼容/开发及验证入口，不再作为日常入口。原 `start_trading_lab.ps1` 的默认启动也委托运行管理器，其验证/开发参数保持兼容。唯一正式行情源是独立 Market Data Agent；具体数据根读取现有配置，不能把 Agent 数据放进源码目录。

Provider 配置：`config/ai.yaml`；凭据与 Telegram：项目根 `.env`，不进入版本控制。修改后用 `tools/restart_web.ps1` 安全加载，不能重复启动连接旧进程后声称配置更新。Telegram 本地测试入口 `tools/test_telegram_push.py`，只有 `--send` 才发送。

测试：`.venv/Scripts/python.exe -B -m unittest discover -s tests -v`；冻结参考验证：`.venv/Scripts/python.exe -B trading_lab.py --verify-baselines`。测试使用隔离账户、时钟、Fake Provider 和 Fake Telegram。

架构与所有权见 `docs/ARCHITECTURE.md`、`docs/DATA_OWNERSHIP.md`、`docs/CONTRACTS.md`。Learning、Research、独立 Decisions、Replay/Simulation 和 Formal ACK 产品已退出；历史账户证据由 Account 自身保存。
