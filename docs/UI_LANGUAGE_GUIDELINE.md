# Trading Lab UI Language Guideline v1

## 适用范围

本规范适用于 Replay、Learning、Decisions、Account 等业务页面。System、Provider、Schema、API、Health 等技术页面可保留必要英文。

## 基本规则

1. 中文是业务页面的主标签、按钮文案、状态解释和错误提示语言。
2. 必须保留的 Contract 枚举显示为中文主词加英文辅助，例如“观察（WATCH）”；传输与持久化仍使用 `WATCH`。
3. Reasoning、Action Policy、Session、Schema 等英文术语只作为括号、小字或技术详情出现。
4. 同一概念在不同页面使用同一中文词，不随机切换“Human Decision / 人工决策 / 人工判断”等写法。
5. 不因界面翻译修改 Schema、数据库枚举、ID 前缀、Provider 参数或冻结协议。

## 业务术语

| 内部或英文名称 | 中文主标签 |
|---|---|
| Human Decision | 人工判断 |
| Human Locked | 人工判断已锁定 |
| Market State | 市场状态 |
| Structure State | 结构状态 |
| Thesis | 核心判断 |
| Key Evidence | 关键证据 |
| Invalidation | 失效条件 |
| Support / Resistance | 支撑位 / 压力位 |
| Confidence | 置信度 |
| Decision Path | 判断路径 |
| Outcome | 后续结果 |
| Human vs AI | 人工判断与 AI 对照 |
| Request AI Review | 请求 AI 独立复核 |
| Keep Previous View | 维持原判断 |
| Submit New Decision | 提交新判断 |
| Reveal Outcome | 揭晓后续走势 |
| Replay Shadow Account | 回放影子账户 |
| Learning Cases | 训练案例 |
| Blind Mode · Human First | 盲测模式 · 人工优先 |

## Action 显示

内部值保持 `NO_ACTION / WATCH / ENTER_TRIAL / ADD / HOLD / REDUCE / EXIT`。界面依次显示“不行动、观察、试探建仓、加仓、持有、减仓、退出”，并在需要精确识别时用括号附上内部值。
