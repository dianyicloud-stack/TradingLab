# 数据观察字段核对（2026-09-16）

范围：现有增强 V2A 表格 → 抽取的原生 `native_core.mjs` → Agent 事实 → 数据观察。
没有修改 `legacy/`、原生计算函数或金额可信度判断。Agent 原始记录仍为唯一市场事实。

## 原版口径核实

`integrations/v2a/V2A_Native_Export_1.1.0.html` 的 `trackerTableMarkup / trackerRowMarkup`：

- “行业涨跌”下的动态板块名称是同一个 `boardChange` 列的副标题。不是另一条价格序列。当前标题来自 Session 确认的 `selectedBoardCode/selectedBoardName`。
- “行业宽度”下的“成分股中位数”也是同一列的说明，对应 `boardMedianChange`。它不是上涨家数占比。
- 原版价格列（开、高、低、当前价）没有涨跌着色，保持中性；没有擅自选择昨收或前行当比较基准。
- 原版允许 `backfillSessionBoardChanges` 等函数重算/补齐部分板块行。本轮不改变它；Agent 仍保存追加 revision。UI 展示该 revision 自带的来源，不把当前板块选择填回未知历史。

## 完整映射

统一保存位置：Agent-owned `OBSERVATION` fact 的 `payload.raw`；API 为 `/api/data-observation/state?view=display` 的 `facts[].payload.raw`。每行按 fact identity + revision 更新。下表 API 字段均相对该 raw；“展示派生”只格式化已有字段，不计算行情指标。

|原版显示名称|原生字段 / 计算来源|API / UI 字段|单位 / 精度|缺失与质量规则|
|---|---|---|---|---|
|输出时点|buildTrackerRow.requestedTime|requestedTime|HH:mm|未知为 —；不能等同市场数据截至|
|统计区间|intervalStart / intervalEnd|interval（展示拼接）|HH:mm–HH:mm|保留原区间，包括即时观察|
|区间开盘|intervalOpen → open|open|元，最多2位|中性；null不转0|
|区间最高|intervalHigh → high|high|元，最多2位|同上|
|区间最低|intervalLow → low|low|元，最多2位|同上|
|当前价|currentPrice → price|price|元，最多2位|行情时间独立显示|
|累计成交量|cumulativeVolume|cumulativeVolume|股，整数|中性|
|Δ成交量|trackerDeltaRows.deltaVolume|deltaVolume|股，整数|非资金净流入；中性|
|累计成交额（原始）|cumulativeAmount → amount|amount|元，最多2位|原值保留，不掩盖待校验|
|成交额状态|amountTrusted / vwapIssue|amountQuality（标签）|已校验/待校验/质量未知/缺失|false 用琥珀色；未知不标已校验|
|Δ成交额|trackerDeltaRows.deltaAmount|deltaAmount|元，最多2位|表与图同源同单位；中性|
|累计换手|turnover|turnover|%，最多2位|不将正值解释为买入|
|Δ换手|trackerDeltaRows.deltaTurnover|deltaTurnover|百分点，最多2位|中性|
|累计VWAP|vwap|vwap|元，最多2位|保留原计算值及质量说明|
|区间VWAP|trackerDeltaRows.intervalVwap|intervalVwap|元，最多2位|空值 —|
|个股涨跌|stockChange|stockChange|%，最多2位|自身正负红/绿|
|行业涨跌|boardChangeAt → boardChange|boardChange|%，最多2位|行级 boardCode/boardName；不以当前选择补历史|
|动态板块名称|Session 已确认 selectedBoardCode/Name|boardChange 表头副标题|名称 + 行提示代码|不同/未知历史来源明确附在该行；不复制旧值到新板块|
|上证|INDEXES.shanghai|shanghai|%，最多2位|原指数计算，null为 —|
|创业|INDEXES.chinext|chinext|%，最多2位|同上|
|北交|INDEXES.beijing|beijing|%，最多2位|同上|
|科创|INDEXES.star|star|%，最多2位|同上|
|同时段量比20日|volumeRatio / volumeRatioSample|volumeRatio；标题读取 parameters.volume_ratio_days|倍，最多2位|允许原生10/20日设置；样本缺失不填0|
|现价-VWAP%|vwapGap|vwapGap|%，最多2位|自身正负红/绿|
|区间涨跌|trackerDeltaRows.intervalChange|intervalChange|%，最多2位|原 comparisonTime，不换基准|
|价格推动效率%/1pp换手|trackerDeltaRows.priceEfficiency|priceEfficiency|%/1pp，最多2位|保留原0.01pp换手门槛，未重算|
|个股-行业Alpha|stockChange−boardChange（原生已有）|alpha|百分点，最多2位|行级板块来源；自身正负红/绿|
|行业宽度|boardMedianChange|boardMedianChange|%，最多2位|原 boardMedianCode / status / capturedAt；无历史值不借用现在值|
|成分股中位数|同上，原版副标题|同一列副标题|同上|不是另造一个宽度指标|
|事件标签|trackerRowsWithEventDetails.eventTags|events（展示标签）|原始文字|不使用AI改写、不推断连续趋势|

额外保留：观察类型（正式/即时）、市场数据截至 `stockDataTime`、最近获取 `capturedAt`。
首次默认全列；常用列为8列；自定义选择保存在当前 origin / USER或TEST / source_generation 范围，尊重旧版已存列选择。

## 缺口分类

1. 本轮补齐的大部分字段原始 raw 已存在，旧 UI 仅列10项，属于展示遗漏。完整 raw 由 Agent 原样保存，未发现上述指标的原核心抽取遗漏，因此没有写新公式。
2. 行业宽度/量比在部分历史时段为 null；为源数据或样本缺口，展示为 —。不承诺本轮补齐市场供应商缺失数据。
3. 当前生产样本部分 raw.boardName / vwapIssue 已含 Unicode replacement characters，而 Session 已确认名称为“膜材料”（BK1439）。这是历史原始文本编码问题；本轮不逆写历史，也不根据当前名称推断过去。行级代码保留，原始文字可在审计查看。
4. 当前收盘样本 amountTrusted=false。恢复字段展示不意味着这些值已满足执行门槛；原执行限制不变。

## 时间修正证据

本轮读取样本：requestedTime=16:13、capturedAt=2026-09-16 16:13:33、stockDataTime=15:00、source=now。
旧 Agent bridge 把 requestedTime 同时当作行情/结构时间。现在即时观察使用已记录 stockDataTime 作为市场时间，仍保留原 requested_at、interval_start/end、available_at。定时观察保留原正式周期。
旧 Opinion/Frozen Input 不被更新；已有 previous eligibility 检查继续排除不合当前时间范围的旧输入。
