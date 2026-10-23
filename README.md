# TradingLab

TradingLab is a local research workspace for mainland China A-share observation. It keeps market facts, asks a configured language model for a structured opinion, and can apply that opinion to a simulated shadow portfolio on this machine. The HTTP server listens on `127.0.0.1` only.

[简体中文](README.zh-CN.md)

## Disclaimer

TradingLab is for research and education. It is not financial, investment, legal, or tax advice, and it is not an offer to buy or sell any security. Market data can be delayed, incomplete, or wrong. Model output can be wrong. The shadow account simulates fills inside this program; it does not place orders at an exchange or a broker. Fee, lot-size, T+1, and calendar behavior are local code covering ordinary Shanghai, Shenzhen, and Beijing A-shares for 2025 and 2026. Unknown years are rejected. That code is not a certification of current exchange rules. You are responsible for API charges, data-vendor terms, and any decision you make.

## Features

The shell registers four pages. `/` redirects to the first enabled page, which is Live.

| Page | Route | What it does |
| --- | --- | --- |
| Live | `/live` | Start or stop the realtime listener, read observed symbols, and keep immutable AI opinions. Auto analysis is `OFF`, `IMPORTANT_ONLY`, or `ALL_EVENTS`. Manual analysis and reanalysis are separate. One execution account is shared by the live symbols. Collapsing a card only changes what you read. |
| 数据观察 | `/data-observation` | Track symbols in the Market Data Agent, show five-minute observations and native events, and export the table. Day, week, and month charts load on demand (unadjusted; volume in shares). A manual end-of-day history task (`HISTORY_EOD`) does not write the live success watermark, the account, or notifications. |
| Account | `/account` | Named simulated portfolios. The account you are viewing is separate from the Live execution account. Modes are `OFF`, `ADVISORY_ONLY` (the default), and `AUTO_SHADOW_EXECUTION`. You can pause new risk, preview a manual simulated open/add/reduce/exit, and read positions and recent operations. |
| System | `/system` | Runtime start, stop, and restart for the web process and the quote collector; market-source status; the default AI provider and model; Telegram notification status; retention preview and apply; diagnostics, including the frozen-file hash check. |

Supporting behavior that is in the code:

- **Market Data Agent.** `market_data_agent.py` is a separate loopback process. A Node.js worker (`engines/live/market_agent/worker.mjs`) does the native calculation over stdin/stdout JSON and uses only Node built-ins. Python stores the facts. The web UI reads them through the agent contract and does not open the agent database. Outbound market HTTP is limited to `sina.cn`, `sina.com.cn`, and `eastmoney.com`.
- **Quotes and history bars.** For a `USER` run, names and last prices of symbols that are not covered by the agent can come from Sina quotes (`adapters/market_quote.py`). Daily bars for the history charts come from Sina (`adapters/history_bars.py`).
- **AI opinions.** Implemented providers are DeepSeek and OpenAI (`adapters/ai/providers`). `config/ai.yaml` also lists MiniMax, Volcengine, and Qwen as disabled entries; those names are not implemented. Reviewed model ids currently include `deepseek-v4-pro`, `deepseek-flash`, `gpt-5.4-mini`, and `gpt-5.4-mini-2026-03-17`. Other ids can be saved as drafts. A successful live opinion is structured JSON (`contracts/live/advisory_opinion_1.0.json`) with actions such as `WATCH`, `HOLD`, `ADD`, `REDUCE`, and `EXIT`. The live AI pool uses at most 8 workers. Historical analysis uses a pool of 2.
- **Shadow account.** A successful live opinion can reach the bound account. `AUTO_SHADOW_EXECUTION` may simulate a fill from automatic or manual live analysis. Historical analysis does not. Orders are checked for cash, position limits, fees, slippage, board lot, and T+1. Creating a portfolio rejects initial capital outside 0.01 to 200,000. The account form uses the same maximum.
- **Telegram.** Optional one-way messages after a successful live opinion whose trigger is `AUTO_EVENT`, `MANUAL`, or `MANUAL_REANALYSIS`, and whose session date is the current Shanghai calendar date. `TEST` runs do not send. The chat id in `.env` must exactly match `TELEGRAM_ALLOWED_CHAT_ID` in `.env.telegram`.
- **Frozen reference.** `python trading_lab.py --verify-baselines` hashes `legacy/` against `docs/frozen_baselines.json`. Exit code 0 means the manifest matches. Exit code 1 means it does not. `legacy/` is not a supported runtime.

## Project structure

```text
trading_lab.py                 CLI entry
market_data_agent.py           Standalone Market Data Agent process
start_trading_lab.ps1          Windows launcher
requirements.txt               Direct dependency ranges
requirements-lock.txt          Pinned distributions
config/                        ai.yaml, live.yaml, activation example
app/shell/                     Loopback HTTP server and composition root
app/live/                      Live and 数据观察 UI
app/account/                   Portfolio UI
app/system/                    Runtime, source, notifications, maintenance
engines/live/                  Listener, opinions, Market Data Agent
engines/account/               Simulated ledger and trading rules
engines/history/               End-of-day bars and history analysis
adapters/                      AI providers, Sina quotes, Telegram, baselines
bridges/                       Agent client and live interval config
contracts/                     JSON schemas and error types
shared/                        Settings, logging, path-scoped stores
tests/                         unittest suite for the current tree
tools/runtime_control.py       Local start, stop, and status
tools/windows/                 Start, stop, and status command files
docs/                          Design notes and the frozen-baseline manifest
legacy/                        Read-only frozen reference
data/                          Local web data (contents are not in Git)
portable-work/                 Windows portable builder and its source lock
dev/                           Windows dev-runtime lock (no download URL)
```

`app/shell/bootstrap.py` is the composition root. Domain modules own their writes. The shell does not implement trading rules.

## Requirements

- **Python 3.11 or newer.** `adapters/baselines.py` uses `hashlib.file_digest`, and `start_trading_lab.ps1` refuses an older interpreter. The checked-in Windows dev/portable checkers expect **Python 3.12.14, 64-bit**. A normal virtualenv can use another 3.11+ build; those checkers will still reject it.
- **Node.js v24.19.0 exactly**, only when you run the Market Data Agent or `--check-agent`. Any other `node --version` string raises `NODE_VERSION_MISMATCH`. Set `TRADING_LAB_NODE` to that executable if another Node is on `PATH`. `--verify-baselines` and `--web-only` do not start the agent worker.
- **Python packages** in `requirements.txt`: `openai`, `PyYAML`, `jsonschema`, `python-dotenv`, `tzdata`. `requirements-lock.txt` pins those packages and their dependencies (25 distributions, verified on Windows Python 3.12). There is no `package.json` and no `npm install`. The Node worker imports only `node:` modules.
- **Windows command files** (`tools/windows/*.cmd`) call `.venv\Scripts\python.exe`. Create the virtualenv at `.venv` or call `tools/runtime_control.py` with another interpreter.
- A browser on the same machine. The UI text is Simplified Chinese. Charts use the vendored TradingView Lightweight Charts 5.0.8 file under `app/live/static/vendor/` (Apache License 2.0).

`dev/runtime-lock.json` describes a Windows x64 runtime zip. Its `download_url` is null. This repository does not publish that zip. Installing from `requirements.txt` does not use it.

## Installation

```bash
git clone https://github.com/dianyicloud-stack/TradingLab.git
cd TradingLab
python -m venv .venv
```

Windows:

```bat
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
copy .env.example .env
copy .env.telegram.example .env.telegram
```

macOS or Linux:

```bash
.venv/bin/python -m pip install -r requirements-lock.txt
cp .env.example .env
cp .env.telegram.example .env.telegram
```

Leave the key fields empty until you want a real model or Telegram call. Both files are gitignored once you copy them off the `*.example` names.

Install Node.js v24.19.0 before starting market collection. Point `TRADING_LAB_NODE` at `node` if needed.

## Quick start

Commands below assume the virtualenv interpreter is `python` on your `PATH`. On Windows that is `.venv\Scripts\python.exe`. On macOS or Linux it is `.venv/bin/python`.

Read-only baseline check (no server, no network):

```bash
python trading_lab.py --verify-baselines
```

Initialize the local stores and print health, without opening HTTP:

```bash
python trading_lab.py --init-only
```

Foreground web process on port 8765, without starting market collection:

```bash
python trading_lab.py --web-only --port 8765
```

The process prints `Trading Lab: http://127.0.0.1:8765` and serves until Ctrl+C. Open `/live`, `/data-observation`, `/account`, or `/system`. `GET /healthz` returns `{"service":"Trading Lab","status":"UP"}`.

Normal local start hands the process to the supervisor and then returns:

```bash
python trading_lab.py
python tools/runtime_control.py status
python tools/runtime_control.py stop
```

On Windows, the daily command files wait for the result. Start opens the page once after the server is ready. Closing the browser leaves the server running.

```bat
tools\windows\TradingLab_Start.cmd
tools\windows\TradingLab_Status.cmd
tools\windows\TradingLab_Stop.cmd
```

`powershell -File .\start_trading_lab.ps1` uses that same desktop start path. Useful switches: `-Port 8765`, `-InitOnly`, `-VerifyBaselines`, `-CheckAgent`, `-StopAgent`, `-Test`, `-PythonPath`.

Optional desktop shortcuts, created by `tools/windows/install_shortcuts.ps1`: `TradingLab 启动`, `TradingLab 停止`, `TradingLab 状态`.

Windows logon startup is a separate per-user scheduled task named `TradingLab-Supervisor-` plus a short hash of the repository path. It is not created by a normal start. It requires `.venv\Scripts\python.exe` and an interactive Windows user. Other operating systems raise `WINDOWS_STARTUP_ONLY_NOT_HOST_TESTED`.

```bat
python tools\runtime_control.py install-startup
python tools\runtime_control.py startup-status
python tools\runtime_control.py disable-startup
python tools\runtime_control.py uninstall-startup
```

`python trading_lab.py --check-agent` prints the configured agent root and the Node version it resolved. It does not start collection. `python trading_lab.py --stop-agent` asks the configured data service to stop and keeps stored facts.

If a web instance is already running, a later start prints that URL and does not create a second data service. A changed agent data root is refused while that instance is up.

### Market collection

Collection stays off until all of the following are true:

1. Node.js is exactly v24.19.0.
2. The agent data directory is an absolute path **outside** this repository. The path must not contain a `legacy` segment. The default is `<parent of this repo>/TradingLabData/MarketDataAgent` on Windows and `/var/lib/tradinglab/market-agent` elsewhere. Override it with `TRADING_LAB_MARKET_AGENT_ROOT`.
3. `<agent-root>/activation.json` has `schema_version` `1.0`, `source` `USER`, `collection_enabled` true, and a non-null `approved_at`. `config/market_agent.activation.example.json` shows the shape with collection left off. The `USER` agent process exits with `AGENT_ACTIVATION_REQUIRED` until that record is approved.
4. You start collection from **System**, or the saved source config has agent auto-start enabled. Starting the agent waits until the Live listener is stopped and no AI task is still running.

Check the agent binary without serving:

```bash
python market_data_agent.py --data-root /absolute/path/outside/this/repo --check
```

`--check` still requires the Node version check. It does not require activation. Do not put this data root inside the git worktree.

## Configuration

| Variable or file | Role |
| --- | --- |
| `.env` | Loaded from the repository root with `override=False`. Holds `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `TRADING_LAB_NODE`, and the Telegram fields below. |
| `.env.telegram` | Local allow-list. `TELEGRAM_ALLOWED_CHAT_ID` must equal `TELEGRAM_CHAT_ID` or Telegram stays `INVALID_CHAT`. The web API cannot set this value. |
| `TELEGRAM_NOTIFICATIONS_ENABLED` | `true` or `false`. Default in the example is `false`. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Used only when notifications are enabled for a `USER` run. `tools/test_telegram_push.py` prints status and does not send. Add `--send` to deliver one test message. |
| `TRADING_LAB_DATA_ROOT` | Web data directory. Default is `data/` under the repository. It must stay inside the repository root. |
| `TRADING_LAB_SOURCE` | `USER` (default) or `TEST`. `TEST` also requires `TRADING_LAB_TEST_RUN_ID`. A `USER` run cannot carry a test run id. |
| `TRADING_LAB_MARKET_AGENT_ROOT` | Absolute agent data directory. See [Market collection](#market-collection). |
| `TRADING_LAB_NODE` | Path to the Node.js v24.19.0 executable. |
| `TRADING_LAB_WATCHER_INTERVAL` | Live loop interval in seconds, from 1 to 3600. Overrides `config/live.yaml`. |
| `config/live.yaml` | `interval_seconds` (default 5) when the environment variable is unset. Loaded for `USER` runs. |
| `config/ai.yaml` | Default provider, model, timeouts, and the environment variable name of each API key. Missing keys surface as `API_KEY_MISSING`. Saving a default affects newly registered tasks. The System "验证连接与输出" action can spend one provider request. |

`TRADING_LAB_LIVE_SOURCE`, `TRADING_LAB_V2A_WORKSPACE`, and `TRADING_LAB_V2A_EXPORT_NAMESPACE` are ignored if present. They do not select a fallback market source.

## Testing

From the repository root:

```bash
python -m unittest discover -s tests -v
python trading_lab.py --verify-baselines
```

On Windows, `start_trading_lab.ps1 -Test` runs the same unittest discovery. The tests under `tests/` build isolated temporary data and use fake providers and a fake Telegram sender. They do not import `legacy/`.

This documentation change does not record a new pass count. Run the commands above on your machine and keep the exit codes you observe.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Please avoid committing secrets, local data, or edits under `legacy/`.

## License

TradingLab is released under the [MIT License](LICENSE). Copyright (c) 2026 dianyicloud-stack.

The chart widget in `app/live/static/vendor/` is TradingView Lightweight Charts, Apache License 2.0, with `LICENSE.lightweight-charts` and `NOTICE.lightweight-charts` beside the file. `portable-work/node-LICENSE.txt` is the Node.js license text kept with the portable runtime notes. It is not a grant to redistribute a Node binary from this repository.
