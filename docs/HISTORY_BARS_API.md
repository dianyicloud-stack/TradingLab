# 日 / 周 / 月历史观察 API

四模块导航不变。历史能力归数据观察 / Live，代码位于 `engines/history`，无 Replay Session。正式历史来源复用新浪日线接口，实时来源仍是独立 Market Data Agent。

## JSON 接口

机器可读 Schema：`contracts/history/bars.schema.json`（`$defs.request` / `$defs.response`）。

- `GET /api/history/bars?symbol=bj920161&period=DAY&end_date=2026-09-24&limit=31&adjustment=NONE&volume_period=WEEK&samples=20`
- `GET /api/history/preferences?symbol=bj920161`
- `PUT /api/history/preferences`：symbol、period、volume_period、samples、limit、adjustment；只保存观察偏好。
- `POST /api/history/analyses`：同 Bars 请求，加唯一 request_id。返回 202、HIST 开头的 id；重复 request_id 幂等，不同参数冲突拒绝。
- `GET /api/history/analyses?before={next_cursor}`：上海本地当天成功结果，按完成时间倒序，每页最多20条；索引引用原Opinion，不返回重复Frozen Input。返回 total/items/next_cursor。
- 默认提交先匹配当天股票、历史日期、两个周期、样本、图表范围、数据版本、服务/模型和思考设置。已有成功结果返回 reused=true；已有进行中任务复用。只有明确传布尔 force_reanalysis=true 才为已成功上下文重新调用Provider，新任务仍用新的request_id。
- `GET /api/history/analyses/{id}`：任务状态、上下文、冻结输入与历史 Opinion；过期返回 EXPIRED / 已按保留策略清理。
- Web 结果入口：`/live?history={id}`。此视图不会启动实时读取、已读标记或账户请求。

period / volume_period 仅 DAY、WEEK、MONTH；samples 为 10、20、30、60；limit 为 1–500，默认31（目标日及前30日）。只支持 NONE 不复权，其他复权方式拒绝；避免把日后发生的复权因子引入历史。股票需明确 sh/sz/bj 前缀。时区 Asia/Shanghai。

响应包含 symbol/exchange/period/timezone/adjustment/source/requested_end_date/actual_end_date/coverage_start/coverage_end/bars/data_version/fingerprint/quality/volume_context。每根 Bar 包含 date/OHLC/volume/amount/complete/source/available_at、源字段、组成日期与数量、缺失日期。volume 单位股；新浪没有提供 amount，固定 null，不通过价格推算。

周/月由日线确定性聚合。Engine 先截断到 end_date，再聚合；未结束周期 complete=false。缺失交易日也使 complete=false。基准市场交易日期来自同一日线来源的上证指数；股票缺失日标为停牌或缺失，不能仅凭缺行判断停牌。无成交不填0参与均值。覆盖起点不足的首周期不参与比较。

完整周期对之前 N 个完整有效周期；未完成周期对之前完整周期的同样第 N 个有效交易日累计量。目标不进入均值，实际样本不足如实报告，不外推补齐。完整周期判断沿用现有交易日历；超出日历支持年份的目标周/月保守标为不完整/日历未知，不猜节假日。

## 来源核查与限制

实测明细见 `history_source_probe.json`。bj920161、sh688601、sz300474 均取得真实日线，OHLC 与不复权价格口径核对；Sina 成交量为股。腾讯对北交所返回空数据、不同市场量单位不同，因此没有混入正式历史链。东方财富试探返回后有连接失败，未作为正式备用。

新浪为最近 N 根接口：实测 1970 根可用、2048 返回空。每次按需选64/256/768/1970容量档并考虑目标距今天的时间，不默认下载几十年。来源未提供可靠日期分页；过早日期返回 OUTSIDE_COVERAGE，不承诺全市场全部上市历史。31根默认和向前加载到500根均受实际覆盖约束。周/月20样本会扩展日线，而非只拿30日假充20周期。

下载可能包含截止日之后的行，Engine 在任何历史计算、返回和AI输入之前剔除；缓存不属于历史AI上下文。原始获取时间与收盘数据时间分离。历史数据为来源当前提供的不复权重建结果，不能宣称是当时原始版本；供应商后续修正风险保留在质量说明中。

## 隔离与生命周期

历史任务仅手动触发，mode=HISTORY_EOD，独立 context_id、SQLite 和 Provider 证据。没有 Account、Telegram、实时 Event、上一轮实时 Opinion 或实时成功游标的依赖。账户上下文固定 null。后端再次校验每根 Bar 和组成日期、量能样本日期及收盘可用时间。成功 Opinion 不可修改，重复启动不自动补发或重试未完成任务。

历史工作根：配置数据根下 `live/history`。日线每股票只保存一个获取日缓存，最多16个股票键、单响应2MiB；周/月按需聚合，不另建永久库。当前日未收盘缓存最长5分钟，收盘后会重新获取，不把盘中截面冒充收盘。任务内容达到16MiB后拒绝新任务，等安全维护，不扩张到无限存储。

历史专属后台每30秒检查上海本地日期，启动时也补查：删除更早获取日缓存，过期已结束历史Opinion/Input及Provider证据、当日索引和任务预算文件；运行任务跳过，跨午夜完成的结果归完成日。即使周末或主维护策略关闭也执行历史轻量TTL，不生成备份。GET不删除数据，跨日旧链接立即显示已清理，正文不再返回；后台分批处理，中断可恢复。保留轻量过期标记30日，偏好永久保留。即使目标日期为2024年，今天获取也归今天工作缓存。普通盘中 Observation/Event 清理仍沿用原所有者与指标保护，不改变其交易日规则。

历史详情的display为只读中文投影，原opinion.analysis不改；技术原文放在折叠诊断中。共用contracts/live/presentation.py术语和成交量规范：标准化为股后，绝对值>=10000除以10000，最多2位小数、去末尾0、后缀W；小于10000保留原数字。2354661→235.47W，32713743→3271.37W。价格/金额/量比不用此格式。前端reading-format.js与后端同用此规范；原API数值仍保留。

图表固定 Lightweight Charts 5.0.8 本地文件，仅展开加载，无运行时CDN；保留 Apache 2.0 LICENSE、NOTICE 和 TradingView 链接。依据：[官方安装及署名说明](https://tradingview.github.io/lightweight-charts/docs/5.0)。小程序复用上述JSON，不复用Web图表代码或重新计算量能。

## 验收约束

首次历史能力验收已完成一个真实任务。本轮结果体验验收不新增真实AI，只读取该成功记录，使用Fake完成重分析测试。每个历史任务实际HTTP最多3次尝试的保护保留；没有额外翻译调用。既有实时Provider、自动资格、输入预算、账户权限保持原值。
