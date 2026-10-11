# Foundation v0.1 验收记录

验收日期：2026-09-05，Windows，本地工作区 `<LOCAL_ORIGINAL_PROJECT>`。

## 环境与命令

- 本机 PATH 未提供 python/py；启动脚本成功自动找到 Codex bundled Python。
- 实际解释器 Python 3.12.14，SQLite 3.53.1；代码要求 Python 3.11+。
- `.\start_trading_lab.ps1 -Test`：**34 tests，全部通过，0 failures，0 errors，0 skipped**（3.801s）。
- `.\start_trading_lab.ps1 -Port 8765`：实际启动成功，绑定 `127.0.0.1:8765`。
- 从其他中文/空格目录执行 `trading_lab.py --init-only`：成功，数据仍只在项目根下初始化。
- `--verify-baselines`：退出码 0，`unchanged=true`，`frozen_baselines=PASS`，两个权威 V2A 检查均为 PASS。

## 对应用户要求的验证

| 项目 | 结果 / 证据 |
|---|---|
| 1. 项目可启动 | Python CLI、PowerShell 启动脚本、真实 loopback 服务通过 |
| 2. 各 Domain 路由 | 七条 HTML 路由全为 HTTP 200，本地 CSS 为 200；浏览器实际验证 System -> Learning 导航 |
| 3. Module Registry | 7 个模块，必需字段齐全；新增 Journal 测试、禁用模块、重复 ID/route 拒绝通过 |
| 4. System Health | 服务 UP；Overall READY；Learning READY；Frozen Baselines READY/PASS；预期未实现状态不降级 |
| 5. learning.db | v1、7 表、21 个不可变 trigger；重复初始化不丢历史；并发修订序号唯一 |
| 6. Account 隔离 | LIVE/REPLAY 辅助目录不同且不嵌套；未来 DB 路径不同；没有生成账户 DB |
| 7. Replay ID | 连续生成 2,000 个 Daily ID 无重复；child 使用 RP-I 前缀 |
| 8. visible_through | 基础模型包含、时区校验、UTC 序列化；判断/修订绑定 case cutoff |
| 9. Legacy 最终冻结 | 只按授权替换了错误的 V2A.1.2.1 副本；最终 81 文件均匹配 manifest v2 |
| 10. V2A hash | 1.2.1 为权威 FROZEN；1.2.2 为 FINAL_ACCEPTED_FROZEN；两项均 PASS |
| 11. 跨域写入防误用 | 拒绝 ../、反斜线、盘符、UNC、ADS、异常 Windows 路径和 junction 逃逸；AST 依赖/页面写入约束通过 |
| 12. Windows 路径 | 中文、空格、正反斜线、无 PATH Python 的启动方式通过 |

补充覆盖：HTTP 写方法 405、任意文件/legacy/DB 路径 404、HTML 字符转义、只读 health probe 错误隔离、
未知 Learning 版本/损坏 trigger 不静默修复、无效 FK 与非有限 JSON 拒绝、UPDATE/DELETE/INSERT OR REPLACE 拒绝、
未来记录在计算前裁定、等于 cutoff 可读、未完成日 K 不可读、子会话不超过 parent cutoff、返回值不污染 Market Cache。

Windows 默认不允许普通用户创建 symlink，测试实际使用 Windows junction 验证相同的路径越界场景，没有跳过。
首轮测试发现测试用 SQLite 连接关闭遗漏造成临时文件占用；修复的是测试夹具，生产 Repository 原本已显式关闭连接。

## 浏览器验收

通过 Codex 本地浏览器访问 `http://127.0.0.1:8765/system`，检查了实际截图：
侧栏、导航、标题、状态卡和健康表正常呈现，没有布局重叠。
点击 Learning 导航后实际到达 `/learning`，DB 显示 READY，七张表计数全为 0。
没有使用模拟行情或假业务结果填充页面。

## 基线修正与验收含义

V2A.1.2.1 已用旧项目权威源替换含外部注入的错误副本，最终 Hash 为 `5fb58532…`。
V2A.1.2.2 内容未修改，最终接受 Hash 为 `fd155f38…`；`c5921ca8…` 只作为 `PRE_FIX_HISTORICAL_SNAPSHOT`。
当前进程 UP，整体 READY。EMPTY、NOT_CONNECTED、NOT_IMPLEMENTED、RESERVED 和 UNKNOWN 属于 Foundation 预期范围状态；
只有真实错误、缺失或警告才会使 Overall 为 DEGRADED。
完整基线身份、主要文件 Hash、Source Audit 结论和文件系统时间观测值在 FROZEN_BASELINES.md 与 frozen_baselines.json。

未执行 legacy 测试、真实 Provider、V2A 实时行情、Account 命令或任何外部服务请求。
市场可知时间/复权/真实 Parquet 的完整 Future Data Guard 集成须在未来 V2D 阶段另行验收。
