# TradingLab

TradingLab 是运行在本机的 A 股研究程序。它保存行情事实，把冻结后的输入交给已配置的语言模型，生成结构化意见，并可以按账户规则记入本机的模拟影子账户。HTTP 服务只监听 `127.0.0.1`。

[English](README.md)

## 风险声明

TradingLab 仅供研究与学习。它不构成金融、投资、法律或税务建议，也不是买卖任何证券的要约。行情可能延迟、不完整或错误。模型输出可能错误。影子账户只在本程序内模拟成交，不会向交易所或券商发送委托。费用、交易单位、T+1 和日历是本地代码，覆盖普通沪深北 A 股，年份只有 2025 与 2026；未知年份会被拒绝。这些规则不是对现行交易所规则的认证。API 费用、数据源条款，以及你据此做出的决定，由你自行承担。

## 功能

壳层注册四个页面。`/` 会重定向到第一个启用的页面，也就是 Live。

| 页面 | 路径 | 作用 |
| --- | --- | --- |
| Live | `/live` | 启动或停止实时监听，查看观察股票，保存不可变的 AI 意见。自动分析的取值为 `OFF`、`IMPORTANT_ONLY` 或 `ALL_EVENTS`。手动分析和重新分析是独立操作。所有实时股票共用一个执行账户。收起卡片只改变阅读，不停止后台。 |
| 数据观察 | `/data-observation` | 在 Market Data Agent 中跟踪股票，显示五分钟观察和原生事件，并可导出表格。日、周、月 K 线按需加载（不复权，成交量单位为股）。手动历史收盘任务（`HISTORY_EOD`）不写实时成功水位、账户或通知。 |
| Account | `/account` | 命名的模拟组合账户。这里切换的是查看账户，不改变 Live 的执行账户。模式为 `OFF`、`ADVISORY_ONLY`（默认）和 `AUTO_SHADOW_EXECUTION`。可以暂停新增风险，预览手工模拟的建仓、加仓、减仓、清仓，并查看持仓与最近操作。 |
| System | `/system` | 启停和重启网页进程与行情采集；数据源状态；默认 AI 服务商和模型；Telegram 通知状态；按策略预览和清理；诊断，其中包括冻结文件哈希检查。 |

代码中的配套行为：

- **Market Data Agent。** `market_data_agent.py` 是独立的本机回环进程。Node.js worker（`engines/live/market_agent/worker.mjs`）通过 stdin/stdout 的 JSON 做原生计算，只使用 Node 内置模块。事实由 Python 保存。网页通过 Agent 合同读取，不直接打开 Agent 数据库。对外行情 HTTP 只允许 `sina.cn`、`sina.com.cn` 和 `eastmoney.com`。
- **报价与历史 K 线。** `USER` 运行时，Agent 未覆盖的股票名称和最新价可以来自新浪行情（`adapters/market_quote.py`）。历史图的日线来自新浪（`adapters/history_bars.py`）。
- **AI 意见。** 已实现的服务商是 DeepSeek 和 OpenAI（`adapters/ai/providers`）。`config/ai.yaml` 里还有未启用的 MiniMax、火山引擎和通义千问条目，注册表没有实现它们。当前已审核的模型 ID 包括 `deepseek-v4-pro`、`deepseek-flash`、`gpt-5.4-mini` 和 `gpt-5.4-mini-2026-03-17`。其他 ID 只能存成草稿。成功的实时意见是结构化 JSON（`contracts/live/advisory_opinion_1.0.json`），动作包括 `WATCH`、`HOLD`、`ADD`、`REDUCE`、`EXIT`。实时 AI 线程池最多 8 个 worker。历史分析线程池为 2。
- **影子账户。** 成功的实时意见可以进入已绑定账户。`AUTO_SHADOW_EXECUTION` 下，实时自动分析或手动立即分析都可能触发模拟成交。历史分析不会。委托会检查现金、仓位上限、费用、滑点、交易单位和 T+1。创建组合时，初始资金必须在 0.01 到 200,000 之间。账户表单使用同一个上限。
- **Telegram。** 成功的实时意见可以单向发一条通知。触发类型须为 `AUTO_EVENT`、`MANUAL` 或 `MANUAL_REANALYSIS`，且意见的交易日是当前上海日历日。`TEST` 运行不发送。`.env` 中的聊天 ID 必须与 `.env.telegram` 里的 `TELEGRAM_ALLOWED_CHAT_ID` 完全一致。
- **冻结参考。** `python trading_lab.py --verify-baselines` 按 `docs/frozen_baselines.json` 校验 `legacy/`。退出码 0 表示一致，退出码 1 表示不一致。`legacy/` 不是可运行的产品。

## 项目结构

```text
trading_lab.py                 命令行入口
market_data_agent.py           独立的 Market Data Agent 进程
start_trading_lab.ps1          Windows 启动脚本
requirements.txt               直接依赖的版本范围
requirements-lock.txt          锁定的完整依赖
config/                        ai.yaml、live.yaml、采集激活示例
app/shell/                     本机 HTTP 服务与组装根
app/live/                      Live 与数据观察界面
app/account/                   组合账户界面
app/system/                    运行、数据源、通知、维护
engines/live/                  监听、意见、Market Data Agent
engines/account/               模拟账本与交易规则
engines/history/               日线与历史收盘分析
adapters/                      AI 服务商、新浪报价、Telegram、基线校验
bridges/                       Agent 客户端与 Live 间隔配置
contracts/                     JSON Schema 与错误类型
shared/                        设置、日志、限定路径的存储
tests/                         当前树的 unittest
tools/runtime_control.py       本机启动、停止、状态
tools/windows/                 启动、停止、状态命令文件
docs/                          设计说明与冻结基线清单
legacy/                        只读冻结参考
data/                          本机网页数据（内容不进入 Git）
portable-work/                 Windows 便携构建及其源码锁
dev/                           Windows 开发运行时锁（没有下载地址）
```

`app/shell/bootstrap.py` 是组装根。各领域模块拥有自己的写入。壳层不实现交易规则。

## 环境要求

- **Python 3.11 或更新版本。** `adapters/baselines.py` 使用 `hashlib.file_digest`，`start_trading_lab.ps1` 会拒绝更旧的解释器。仓库里的 Windows 开发与便携检查要求 **Python 3.12.14，64 位**。普通虚拟环境可以使用其他 3.11+ 构建；那些检查器仍会拒绝它。
- **Node.js 必须正好是 v24.19.0**，仅在运行 Market Data Agent 或 `--check-agent` 时需要。其他 `node --version` 会触发 `NODE_VERSION_MISMATCH`。若 `PATH` 上是别的 Node，把 `TRADING_LAB_NODE` 指到这个可执行文件。`--verify-baselines` 和 `--web-only` 不会启动 Agent worker。
- **Python 包**见 `requirements.txt`：`openai`、`PyYAML`、`jsonschema`、`python-dotenv`、`tzdata`。`requirements-lock.txt` 锁定这些包及其依赖（25 个发行版，在 Windows Python 3.12 上核对过）。没有 `package.json`，也不需要 `npm install`。Node worker 只导入 `node:` 模块。
- **Windows 命令文件**（`tools/windows/*.cmd`）调用 `.venv\Scripts\python.exe`。请把虚拟环境放在 `.venv`，或改用其他解释器直接调用 `tools/runtime_control.py`。
- 同一台机器上的浏览器。界面文字是简体中文。图表使用 `app/live/static/vendor/` 中随仓库提供的 TradingView Lightweight Charts 5.0.8（Apache License 2.0）。

`dev/runtime-lock.json` 描述一份 Windows x64 运行时压缩包，其中 `download_url` 为空。本仓库不发布该压缩包。用 `requirements.txt` 安装时不需要它。

## 安装

```bash
git clone https://github.com/dianyicloud-stack/TradingLab.git
cd TradingLab
python -m venv .venv
```

Windows：

```bat
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
copy .env.example .env
copy .env.telegram.example .env.telegram
```

macOS 或 Linux：

```bash
.venv/bin/python -m pip install -r requirements-lock.txt
cp .env.example .env
cp .env.telegram.example .env.telegram
```

在需要真实模型或 Telegram 调用之前，密钥字段保持为空。从 `*.example` 复制出来的文件已被 `.gitignore` 排除。

启动行情采集前安装 Node.js v24.19.0。需要时用 `TRADING_LAB_NODE` 指向 `node`。

## 快速开始

下面的 `python` 指虚拟环境解释器。Windows 上是 `.venv\Scripts\python.exe`，macOS 或 Linux 上是 `.venv/bin/python`。

只读基线检查（不启动服务，不访问网络）：

```bash
python trading_lab.py --verify-baselines
```

初始化本地存储并打印健康状态，不打开 HTTP：

```bash
python trading_lab.py --init-only
```

在 8765 端口前台运行网页，不启动行情采集：

```bash
python trading_lab.py --web-only --port 8765
```

进程会打印 `Trading Lab: http://127.0.0.1:8765`，直到 Ctrl+C。可打开 `/live`、`/data-observation`、`/account`、`/system`。`GET /healthz` 返回 `{"service":"Trading Lab","status":"UP"}`。

日常本机启动会把进程交给 Supervisor，然后返回：

```bash
python trading_lab.py
python tools/runtime_control.py status
python tools/runtime_control.py stop
```

在 Windows 上，日常命令文件会等待结果。启动成功后打开一次页面。关掉浏览器不会停止服务。

```bat
tools\windows\TradingLab_Start.cmd
tools\windows\TradingLab_Status.cmd
tools\windows\TradingLab_Stop.cmd
```

`powershell -File .\start_trading_lab.ps1` 走同一条桌面启动路径。可用开关：`-Port 8765`、`-InitOnly`、`-VerifyBaselines`、`-CheckAgent`、`-StopAgent`、`-Test`、`-PythonPath`。

`tools/windows/install_shortcuts.ps1` 可在桌面建立三个快捷方式：`TradingLab 启动`、`TradingLab 停止`、`TradingLab 状态`。

Windows 登录自动启动是另一项按用户注册的计划任务，名称是 `TradingLab-Supervisor-` 加上仓库路径的短哈希。普通启动不会创建它。它要求存在 `.venv\Scripts\python.exe`，并且当前用户是交互式用户。其他操作系统会抛出 `WINDOWS_STARTUP_ONLY_NOT_HOST_TESTED`。

```bat
python tools\runtime_control.py install-startup
python tools\runtime_control.py startup-status
python tools\runtime_control.py disable-startup
python tools\runtime_control.py uninstall-startup
```

`python trading_lab.py --check-agent` 打印已配置的 Agent 根目录和它解析到的 Node 版本，不开始采集。`python trading_lab.py --stop-agent` 要求已配置的数据服务停止，并保留已有事实。

若网页实例已在运行，再次启动会打印现有地址，不会再建一套数据服务。该实例运行期间，改变 Agent 数据根会被拒绝。

### 行情采集

采集保持关闭，直到同时满足：

1. Node.js 正好是 v24.19.0。
2. Agent 数据目录是本仓库**之外**的绝对路径，路径各段不能叫 `legacy`。Windows 默认是 `<本仓库的父目录>/TradingLabData/MarketDataAgent`，其他系统默认是 `/var/lib/tradinglab/market-agent`。可用 `TRADING_LAB_MARKET_AGENT_ROOT` 覆盖。
3. `<agent-root>/activation.json` 的 `schema_version` 为 `1.0`，`source` 为 `USER`，`collection_enabled` 为 true，且 `approved_at` 非空。`config/market_agent.activation.example.json` 是采集关闭时的形状。在这份记录获准之前，`USER` 的 Agent 进程会以 `AGENT_ACTIVATION_REQUIRED` 退出。
4. 从 **System** 页面启动采集，或已保存的来源配置打开了 Agent 自动启动。启动 Agent 前，Live 监听须已停止，且没有仍在运行的 AI 任务。

不启动服务、只检查 Agent 程序：

```bash
python market_data_agent.py --data-root /absolute/path/outside/this/repo --check
```

`--check` 仍会检查 Node 版本，不要求激活记录。不要把这个数据根放进 Git 工作区。

## 配置

| 变量或文件 | 作用 |
| --- | --- |
| `.env` | 从仓库根加载，`override=False`。存放 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`TRADING_LAB_NODE`，以及下面的 Telegram 字段。 |
| `.env.telegram` | 本机允许名单。`TELEGRAM_ALLOWED_CHAT_ID` 必须等于 `TELEGRAM_CHAT_ID`，否则 Telegram 状态为 `INVALID_CHAT`。网页 API 不能设置这个值。 |
| `TELEGRAM_NOTIFICATIONS_ENABLED` | `true` 或 `false`。示例里的默认值是 `false`。 |
| `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` | 仅在 `USER` 运行且通知已启用时使用。`tools/test_telegram_push.py` 只打印状态，不发送。加上 `--send` 才会投递一条测试消息。 |
| `TRADING_LAB_DATA_ROOT` | 网页数据目录。默认是仓库下的 `data/`。必须留在仓库根之内。 |
| `TRADING_LAB_SOURCE` | `USER`（默认）或 `TEST`。`TEST` 还必须设置 `TRADING_LAB_TEST_RUN_ID`。`USER` 运行不能带测试运行 ID。 |
| `TRADING_LAB_MARKET_AGENT_ROOT` | Agent 数据目录的绝对路径。见[行情采集](#行情采集)。 |
| `TRADING_LAB_NODE` | Node.js v24.19.0 可执行文件的路径。 |
| `TRADING_LAB_WATCHER_INTERVAL` | Live 循环间隔，单位秒，范围 1 到 3600。覆盖 `config/live.yaml`。 |
| `config/live.yaml` | 未设置环境变量时的 `interval_seconds`（默认 5）。`USER` 运行会加载它。 |
| `config/ai.yaml` | 默认服务商、模型、超时，以及每个 API 密钥对应的环境变量名。缺少密钥时状态为 `API_KEY_MISSING`。保存默认值只影响新登记的任务。System 页面的「验证连接与输出」可能消耗一次服务商请求。 |

若环境里存在 `TRADING_LAB_LIVE_SOURCE`、`TRADING_LAB_V2A_WORKSPACE`、`TRADING_LAB_V2A_EXPORT_NAMESPACE`，它们会被忽略，不能用来切换备用行情源。

## 测试

在仓库根目录：

```bash
python -m unittest discover -s tests -v
python trading_lab.py --verify-baselines
```

在 Windows 上，`start_trading_lab.ps1 -Test` 执行同一套 unittest 发现。`tests/` 下的测试使用隔离的临时数据、伪造的 Provider 和伪造的 Telegram 发送器，不会导入 `legacy/`。

这次文档变更没有记录新的通过数量。请在你的机器上运行上述命令，并保留你看到的退出码。

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。请不要提交密钥、本机数据，或 `legacy/` 下的修改。

## 许可证

TradingLab 以 [MIT License](LICENSE) 发布。Copyright (c) 2026 dianyicloud-stack。

`app/live/static/vendor/` 中的图表组件是 TradingView Lightweight Charts，许可证为 Apache License 2.0，同目录有 `LICENSE.lightweight-charts` 和 `NOTICE.lightweight-charts`。`portable-work/node-LICENSE.txt` 是随便携运行时说明保留的 Node.js 许可证文本，并不表示可以从本仓库再分发 Node 二进制文件。
