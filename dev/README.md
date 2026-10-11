# TradingLab Windows x64 开发环境

本轮仅建立 STEP 03 环境。Python 3.12.14 x64、Node 24.19.0、25 项 Python 依赖由 `runtime-lock.json` 锁定。使用 Windows 自带 Windows PowerShell 5.1；不需要全局 Python、Node、pip 或 npm。

## 第二台 PC 恢复

1. 获取完整源码和独立制品 `tradinglab-dev-runtime-win-x64-20261011.1.zip`，放入工程 `.dev/artifacts/`。文件名、大小和 SHA-256 必须与锁清单一致。当前没有下载 URL；认证下载尚未实现，不回退系统解释器。
2. 运行根目录 `Setup-Dev.cmd`。也可 `Setup-Dev.cmd -Artifact "压缩包的绝对路径"`。从其他工作目录调用时应提供入口的绝对路径。
3. 运行 `Check-Dev.cmd`；通过后运行 `Start-Dev.cmd`。DEV 页面为 `http://127.0.0.1:18765`，Agent 为 18766。端口可在 `dev/dev-config.json` 修改，但必须不同且空闲。
4. 使用 `Stop-Dev.cmd` 正常关闭。不要通过产品页的 USER Supervisor 启停 DEV：该入口未改业务逻辑，不属于 DEV 生命周期。重复 Stop 安全。

启动窗显示 DEV / TEST。Web、Agent 均使用 TEST 身份；Core 为 `.dev/data`，Agent 为 `.dev/agent`。Agent 默认暂停且无真实行情网络。真实 AI 子进程、外部 Python 网络及越界数据库/写入由启动包装器拒绝；Telegram 依照既有 TEST 规则不投递。入口不会加载原项目 `.env`。若本工程根 `.env` 存在非空配置，检查失败；无密钥模板位于 `.dev/dev.env`，不要填入真实凭据。

Windows Job 管理本次创建的进程树；正常关闭使用现有带 token 的本地生命周期接口，核对 PID 创建时间、真实解释器、工程、TEST 身份、数据根、端口和实例。失败回收仅限本次启动 Job；未知进程保护未放宽。诊断在 `.dev/logs`，控制文件含本地控制 token，禁止提交或共享原始 `.dev`。

## 环境修复与许可

Setup 总是先校验制品，再校验全部 Runtime。正确环境直接复用；清单外文件、缺失文件、版本差异、链接或损坏均停止。`.venv` 使用固定解释器重新创建，依赖来自已封印 site-packages，未复制原项目 `.venv`，不含 pip。不要在此环境临时安装升级依赖；依赖变更需要单独更新审核过的锁与制品。

移动工程后旧 `.venv` 和 DEV 数据归属会因绝对路径不符而拒绝使用。先停止 DEV，保存诊断，将**本工程生成的** `.venv`、`.dev/venv-seal.json`、`.dev/data`、`.dev/agent`、`.dev/data-ownership.json` 移到本工程 `.dev` 下的新备份目录，再重新 Setup，创建新的 TEST 数据。不要移动/删除源项目环境。损坏 Runtime 同理保留后移走本工程 `.dev/runtime`，从锁定 ZIP 恢复。已有非空数据目录缺少归属标记时拒绝接纳，不检查或导入其数据库内容。

制品只含 RC1 `runtime/python`、`runtime/node`，共 3,378 文件；许可证清单和各文件 SHA 位于锁清单。Python 标准库/DLL、25 项分发元数据及相关许可证随制品保留。来源是已审核 RC1 文件封印；没有新增上游签名验证声明。打包源码 `tools/dev/package_runtime.py --rc1 <只读RC1根>` 只提取并验证这两个子树，不调用 Portable 构建器。输出已存在会拒绝覆盖。

## 测试与可选浏览器工具

原有 tests 源码未修改。受控复制验证工具为 `tools/dev/validate_step03.py`，使用 `.venv/Scripts/python.exe -I -B -X utf8` 调用：首次依次 `prepare`、`entries`、`suite`；所有副本、数据、日志在 `.dev/validation`。`prepare` 拒绝覆盖既有证据。开发后应使用新的验证副本，设置进程环境变量 `TL_DEV_VALIDATION_NAME` 为新的相对目录名再执行上述流程。`negative` / `final` 是 STEP 03 的故障注入验收，会临时修改该验证副本并恢复，不能对正式项目使用。

`suite` 执行原有 `python -m unittest discover -s tests -v` 和 `python trading_lab.py --verify-baselines`，保留原退出码和日志。2026-10-11 本机：431 项，417 PASS、1 FAIL、13 SKIPPED；两份冻结基线均 PASS。原失败不得解释成环境检查全绿。Fake Provider、合成行情与 TEST Account 的实际链路由原 `test_agent_auto_closure` / 账户测试验证。Portable 布局专用测试另列 NOT_TESTED，等待 STEP 04 制品布局。

日常 Web、Agent、Worker 不需要浏览器自动化。29 个工具文件仅替换本机 Node/Codex/Chrome/Playwright 定位，未改变断言。浏览器工具从 `.dev/e2e/node_modules/playwright` 或 `TRADING_LAB_PLAYWRIGHT_ROOT` 加载 Playwright **1.62.1**；浏览器锁见 `browser-lock.json`（Chromium 151.0.7922.34 / revision 1234）。默认浏览器目录 `.dev/e2e/browsers`，可通过 `PLAYWRIGHT_BROWSERS_PATH` / `TRADING_LAB_CHROME` 显式配置。需要另行取得对应版本的 E2E 包和浏览器；本轮未下载/执行，NOT_TESTED。当前 Runtime 仅含 node.exe，不带 npm；没有假称 E2E 已一键恢复。

历史生产探针、快照工具和旧 Portable 构建器仍有旧路径/生产端口，不由 DEV 入口执行。`Check-Dev` 把这些引用列入 `.dev/tool-dependencies.json`，不把历史工具标为可安全运行。其余构建改造留待 STEP 04，AGENTS 阶段文字留待 STEP 05。禁止把 `.dev`、`.venv`、Runtime ZIP、真实 `.env` 或数据库加入普通 Git。

本机恢复与启动 PASS；第二台 PC NOT_TESTED。详细证据见根目录 STEP 03 报告。
