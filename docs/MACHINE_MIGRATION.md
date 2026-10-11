# 当前标准启动与迁机（Agent 单一来源）

本说明适用于 2026-09-18 收口代码。代码在磁盘不等于正式进程已加载；本轮部署等待集中确认。
正式入口仍为 `http://127.0.0.1:8765`，唯一启动脚本为项目根 `start_trading_lab.ps1`。
Live、数据观察、System、Advisory 共用 MARKET_AGENT / MARKET_DATA_AGENT；没有旧 Workspace 回退。

## 最小迁移清单

1. 停止旧机器对应写入进程后，备份当前项目代码与必要 `data`（Account、Learning、Decisions、Opinion/Input、Live runtime、System 配置）。SQLite 正式备份应使用所有者备份或停机一致副本，不能只复制正在写入的主 DB。
2. 单独迁移完整 MarketDataAgent 数据根，包含事实、原生协议文件、删除归档、Session 分配下限和批准采集的 `activation.json`。连接描述是进程 Runtime，新 Agent 会重新发布；不要输出其中凭据。
3. 在新机器安装本机 Python 3.11+、Node **24.19.0**。重新创建 `.venv` 并执行 `.venv\Scripts\python.exe -m pip install -r requirements-lock.txt`。不要复制另一台机器的 `.venv` 或依赖 Codex 缓存解释器。Node 可在 PATH，或用本项目进程的 `TRADING_LAB_NODE` 指定本机路径。
4. System 的 `data/system/market-source.json` 保存 Agent 根、`agent_auto_start`、稳定 `source_generation`。环境 `TRADING_LAB_MARKET_AGENT_ROOT` 或明确 CLI `--market-agent-root` 可覆盖根，作为诊断显示；不要同时连接两份相同数据身份的可写复制品。Linux 预留 `/var/lib/tradinglab/market-agent`，本轮没有宣称 Linux 实测。
5. 通过原凭据配置方式在新机器配置 Provider；不随报告或公共归档搬运密钥。启动不会授予新的 AI、Listener 或账户自动执行权限。
6. 执行 `start_trading_lab.ps1 -CheckAgent` 和 `tools/market_agent_preflight.py` 检查依赖/配置，不启动采集。确认后用 `start_trading_lab.ps1` 启动 Web。仅当原有 `agent_auto_start` 和有效 `activation.json` 都允许时才维持 Agent 生命周期；否则明确显示不可用。
7. 确認 System、数据观察、Live 的 owner/root/generation 一致，旧 Session、Opinion 和持仓历史可读。Agent 重启改变进程 PID，不改变数据 generation，不重置事实或成功 Cursor。

不再需要：V2AWorkspace、旧 HTML、cutover.json、旧跟踪导入或旧切源操作。
旧 `TRADING_LAB_LIVE_SOURCE`、`TRADING_LAB_V2A_WORKSPACE` 和 export namespace 残留只产生有限弃用提示，绝不用于选择来源。
启动时 System 执行 source schema v2 幂等迁移：原配置按 SHA256 原样备份到 `data/system/source-history/`，旧 operations 完整保留；自动启动权限不扩大。
旧切源/回退/导入 API 返回 `410 SOURCE_SWITCHING_RETIRED`。

## 不可用与恢复

Agent 不可用时检查本机依赖、配置根、activation 和单写者占用；Web 保持可读错误状态，不读取旧源。
恢复使用同一 Agent 数据根和稳定 generation；不重置市场事实、账本或成功 Cursor。
回退代码必须保留本轮单 Agent 来源约束。不能用旧版本直接恢复 V2A 读取；必要时关闭监听、停在明确不可用状态，再修复 Agent。
历史 Workspace 归档只供审计，不是启动依赖或可选行情源。
