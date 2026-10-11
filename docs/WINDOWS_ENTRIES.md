# Windows 日常使用

双击当前用户桌面「TradingLab 启动」「TradingLab 停止」「TradingLab 状态」。快捷方式指向项目 `tools/windows` 下同名用途的 cmd，工作目录为项目根，调用项目自己的 `.venv`。

- 启动：复用现有 Supervisor，缺失时启动；等待轻量健康检查后交给默认浏览器打开 `/live`。同一 Web 实例仅自动打开一次，重复点击不会重复服务或网页。若之后自行关闭了网页，可直接打开 http://127.0.0.1:8765/live。浏览器打开失败不影响已经运行的后台。
- 停止：通过现有正常停止接口停止 Web 与 Agent，等待运行任务完成，不使用强制终止。按既有合同，轻量 Supervisor 留下待命。Listener 的长期 ENABLED/DISABLED 不变，下次启动依原设置恢复；休市时等待开市。异常停止不会自动升级为 force-stop。
- 状态：中文状态窗口保持打开，按任意键关闭。服务离线时仍显示监听期望；账户等设置如来自上次只读查询，会标明记录时间及未重新核对，不冒充当前值。

Windows 登录自启动已通过 `disable-startup` 禁用，原任务定义保留；可用 `.venv\Scripts\python.exe -B tools\runtime_control.py install-startup` 显式恢复。不改变其他计划任务。

丢失快捷方式时，运行 `tools/windows/install_shortcuts.ps1` 可重建这三个快捷方式。项目 cmd 本身也可直接双击。

`trading_lab.py` 是内部兼容、开发及验证入口，仍由 Supervisor 调用。不要删除。旧 `start_trading_lab.ps1` 的日常启动已委托运行管理器，特殊开发/基线验证参数保留。

新代码只增加 System 的命令行展示、有限等待与浏览器交接；cmd/快捷方式不拥有 PID、端口或业务规则。不改变市场、AI、账户、通知或 Supervisor 状态机。

## 2026-09-26 实机核验

- 通过正式 disable-startup 禁用计划任务，核对禁用前后三个服务实例未变。既有管理者正常退出后任务状态为 Disabled，定义仍存在；随后由手动入口创建独立后台。
- 实际执行两个停止/启动周期。首次从三个服务全部停止的状态启动；后一次按原合同保留 Supervisor 后启动。Listener 长期 ENABLED、listener_revision=9、原启用边界均保留，恢复为休市等待。
- 重复运行启动入口，三个实例及浏览器交接记录未改变。启动命令退出、只读测试浏览器关闭后，后台仍运行。未关闭用户其他浏览器窗口。
- 三个桌面 .lnk 的目标和工作目录通过 Windows COM 回读核验。状态入口在线/离线均正常，窗口含 pause；离线设置明确标记历史测量时间。
- 10 项新增桌面入口测试与 1 项既有长任务安全收尾/监听保留测试通过；四个正式页面 HTTP 200，pageerror=0、console.error=0。Legacy 81 文件 changes=[]，两份权威基线 PASS。
- 账户绑定/模式/新增风险、AI 配置及 Telegram 状态和发送计数与实施前一致。未触发真实 AI、测试通知或交易。
- 当前 Web build：d2877bcc66e128cf；本轮未改变 Web 业务代码。运行管理公共 build：67b2ec4d4a614bf2。简要前后状态见 windows_entry_before.json / windows_entry_after.json。
