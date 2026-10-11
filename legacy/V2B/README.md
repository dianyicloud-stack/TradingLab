# V2B Coordinator A+B.2

这是一个独立于现有行情页面运行的旁路实验层，用于验证：

`模拟 IMPORTANT Event → Event Handoff → AI Provider → Decision → Schema Validation → JSONL/usage 日志`

## 冻结边界

- `量价查询_V2A.1.2_五分钟状态驱动最终冻结版.html` 未被修改。
- V2B 不读取或改写 V2A.1.2 的运行文件，不接现有 Event Ledger、Handoff 或 ACK。
- 当前没有 Telegram、手机/PC ACK、真实 5 秒 Detector、Account Engine 或自动交易。
- 当前实现 DeepSeek 与 OpenAI Provider；MiniMax、Volcengine、Qwen 仅保留配置槽位。

## 架构

- `v2b_coordinator.py`：CLI 入口。
- `coordinator/config_manager.py`：配置、`.env` 与 Provider 选择优先级。
- `coordinator/event_manager.py`：从模拟事件生成完整 Event Handoff，并在 JSON Schema 通过后继续执行 cursor、session、日期和 Observation 的语义校验。
- `coordinator/job_manager.py`：按显式 transition map 追加记录 `QUEUED/RUNNING/RESULT_READY/FAILED`。
- `coordinator/decision_manager.py`：合并可信元数据并严格校验统一 Decision。
- `coordinator/usage_manager.py`：记录 token、延迟、请求结果与可选成本。
- `providers/base.py`：统一 `AIProvider.analyze_event()` 接口。
- `providers/openai_provider.py`：OpenAI Responses API 适配器。
- `providers/deepseek_provider.py`：通过 OpenAI Python SDK 连接 DeepSeek Responses API，使用 Thinking 与 JSON Schema Structured Outputs。

Coordinator 只调用 Provider Interface。以后新增 Provider 时，不需要改动事件、Job、Decision 与持久化主流程。

## 安装

建议在 `V2B` 目录创建隔离环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

默认 Provider 是 DeepSeek，在本机 `.env` 中填写 `DEEPSEEK_API_KEY` 后可执行真实 Gate B；需要显式测试 OpenAI 时填写 `OPENAI_API_KEY`。真实 `.env` 已被 `.gitignore` 排除。程序不会在 doctor、普通日志、Decision、Handoff 或 usage 中输出密钥。

## 配置

`config.yaml` 中：

- `ai.default_provider` 是默认 Provider。
- 单次 CLI `--provider` 优先于 session Provider，session Provider 优先于默认值。
- DeepSeek/OpenAI 模型、超时、有限重试和输出 token 上限均从配置读取；默认配置为 `deepseek-v4-pro`、Thinking High。
- 未实现 Provider 会返回 `PROVIDER_NOT_IMPLEMENTED`，不会偷偷回退到 OpenAI。
- Provider 是否已实现只由 `providers.PROVIDER_REGISTRY` 决定；配置中的 `enabled` 仅表示用户是否启用。
- `pricing` 为空或必要价格缺失时 `cost_usd` 为 `null`，避免把未知价格按零计费；如需估算成本，可配置每百万 token 的输入、缓存输入和输出价格。

## CLI

检查配置、依赖和密钥是否存在（只显示 `configured/missing`）：

```powershell
.\.venv\Scripts\python.exe v2b_coordinator.py doctor
```

查看 Provider 状态：

```powershell
.\.venv\Scripts\python.exe v2b_coordinator.py providers
```

生成 Event Handoff，不调用 API：

```powershell
.\.venv\Scripts\python.exe v2b_coordinator.py simulate
```

使用默认 DeepSeek Provider 分析模拟事件：

```powershell
.\.venv\Scripts\python.exe v2b_coordinator.py analyze --event samples/simulated_event.json
```

单次明确指定 OpenAI：

```powershell
.\.venv\Scripts\python.exe v2b_coordinator.py analyze --event samples/simulated_event.json --provider openai
```

DeepSeek 使用 `https://api.deepseek.com`、Responses API 和 `reasoning.effort=high`。Provider 内部 SDK 重试固定为0，有限重试仍统一由 Coordinator 执行。当前不硬编码 DeepSeek 动态时段价格，因此 usage 正常记录而 `cost_usd` 为 `null`。

分析一个已经冻结的 Handoff（不会重新生成 ID、时间或 cursor）：

```powershell
.\.venv\Scripts\python.exe v2b_coordinator.py analyze-handoff --handoff state/last_simulated_handoff.json --provider openai
```

## Event Handoff

Handoff 类型固定为 `EVENT_INTERRUPT`，包含单股票完整上下文：tracking session、上次 Decision checkpoint、完整增量事件、触发事件、Composite Event、checkpoint 后观察路径、约 120 秒 runtime context、current state、冻结 cursor 和 metadata。

`events_since_checkpoint` 必须精确、连续地覆盖 `last_processed_event_seq + 1` 到 `handoff_max_event_seq`；触发事件必须包含在未处理增量中，Composite 引用必须能在该增量内找到。`observation_rows_since_checkpoint` 必须是 checkpoint 后严格递增、无重复的正式 Observation，最新一条必须精确等于冻结 observation max；空数组时冻结 max 必须等于 last processed，禁止用 cursor 跨过未发送给模型的数据。

Schema 校验后还会检查上述 completeness 规则，以及 tracking session 与 session date 一致性。语义失败使用 `HANDOFF_SEMANTIC_VALIDATION_FAILED`，并在创建 Job 前终止。

模拟数据全部位于 `samples/`，不依赖真实行情或 V2A 文件。

## Decision

所有 Provider 最终进入相同的 `decision.schema.json`。系统生成并覆盖以下可信字段：

- `decision_id`
- `provider`
- `model`
- `handoff_id`
- `tracking_session_id`
- `symbol`
- `analyzed_at`
- `processed_through_seq`
- `processed_through_observation_time`

模型只负责 `market_state`、`structure_state`、`action`、`key_levels`、`invalidation`、`reason_summary` 和 `confidence`。两个处理游标由系统精确复制 Handoff 的冻结 maxima，模型即使返回同名字段也会被忽略。Validator 检查 ID 一致性、action 枚举、key levels、reason summary，以及最终游标必须与冻结 maxima 完全相等。非法 Decision 会令 Job 进入 `FAILED`，不会写入 `decisions.jsonl`。

Action 是 Market Decision，不是账户执行命令：`HOLD` 表示核心结构假设仍成立，`WATCH` 表示出现重要变化但证据不足，`EXIT` 表示原市场结构假设已失效，`NO_ACTION` 表示没有足够新信息或数据。

Job 允许 `QUEUED → RUNNING/FAILED`、`RUNNING → RUNNING/RESULT_READY/FAILED`。其中 `QUEUED → FAILED` 专用于 Provider 初始化等运行前失败，`RUNNING → RUNNING` 只允许 attempt 严格递增的重试；终态不能再转换。非法转换使用 `JOB_INVALID_TRANSITION`。

## 测试

Mock 测试不需要 API Key 或网络：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m "not integration"
```

真实 DeepSeek/OpenAI 测试都是可选的：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -s -m integration
```

没有对应 API Key 时，真实测试显示 `SKIPPED`，不计为失败。

## 持久化与日志

- Job 每次状态变化追加到 `state/jobs.jsonl`。
- 合法 Decision 追加到 `state/decisions.jsonl`。
- 每次 API 请求的 token、latency、request ID、success/error 与 fallback 状态追加到 `logs/api_usage.jsonl`。
- 可定位问题的简要阶段日志写入 `logs/coordinator.log`。

这些文件均为 append-only 运行记录；不会无痕覆盖旧 Job 或 Decision。日志只保存定位所需的 ID、阶段与简短错误，不记录 API Key、Authorization header、完整 `.env` 或巨大 Handoff。

## 人工消费 V2A ACK Receipt

V2A 成功应用人工 ACK 后，在它的运行目录生成 `ack_receipt.json`。仅当人工明确执行以下命令时，V2B 才读取指定文件；不扫描或监视 V2A 目录，也不修改 V2A。

```powershell
.\.venv\Scripts\python.exe v2b_coordinator.py ack consume --receipt "D:\V2A运行目录\ack_receipt.json"
.\.venv\Scripts\python.exe v2b_coordinator.py ack status
```

消费顺序：Receipt Schema 校验 → 匹配当前 pending ACK 的身份/两个应用 Cursor → 比对 `ack_payload` → 复核 Decision/Job/人工 ACCEPT Review 及冻结请求 → 追加消费事实 → 原子保存最新回执 → 删除 pending ACK。

- Receipt 规则位于 `schemas/ack_receipt.schema.json`，不改变 Decision/Handoff Schema。只接受 `1.0 / ACK_APPLIED / APPLIED / V2A`；序号为非负安全整数，观察时间为 `null` 或 `HH:mm`。时间戳必须是带时区的有效日期时间；拒绝重复 JSON 键、非有限数值。V2A 的 `directory_id` 等扩展字段保留。
- `ack_payload` 的 14 个协议字段使用排序键、紧凑分隔符的 canonical JSON 比对。V2A 不回传 V2B `generated_at`，所以该元数据不要求存在，不影响协议匹配。
- 追加到 `state/ack_consumptions.jsonl`，包含消费 ID、所有链路 ID、实际 Cursor、`CONSUMED` 状态，以及完整 Receipt 的 `receipt_sha256`。历史记录不覆盖。
- `state/last_ack_receipt.json` 是可覆盖的最新验证回执。两次落盘都成功后才删除 `state/pending_ack.json`；其他人工历史不删除、不修改。
- 与人工 ACCEPT 共用 `decision_reviews.lock`，保护校验、幂等判断及提交。消费期间有未完成 ACCEPT 事务时拒绝消费，需先重试原 ACCEPT。
- 同一 Receipt 重复导入返回 `already_consumed=true`；正常完整重复不写文件，不再次追加。相同 Receipt ID 的不同内容返回 `RECEIPT_ID_CONFLICT`，同 ACK ID 的不同 Receipt 返回 `ACK_RECEIPT_CONFLICT`。旧回执不能清除后来生成的新 pending ACK，也不能覆盖较新的回执快照。
- 落盘或删除失败返回 `ACK_CONSUMPTION_INCOMPLETE`，保留 pending。重试同一 Receipt 会以已有消费事实为依据补齐快照/清理，不重复追加。损坏或截断的消费账本会拒绝操作并保留 pending，需先人工核对，不会重写历史。
- `ack status` 优先显示 `PENDING`；没有 pending 时显示最近 `CONSUMED`；均不存在则 `NONE`。状态查询不会自动消费。

错误分类：`RECEIPT_SCHEMA_INVALID`、`NO_PENDING_ACK`、`RECEIPT_ACK_MISMATCH`、`RECEIPT_ACK_PAYLOAD_MISMATCH`、`ACK_AUDIT_CHAIN_INVALID`。读取/存储故障另有 `RECEIPT_READ_ERROR`、`ACK_CONSUMPTION_STORAGE_ERROR`。

专门测试（隔离临时目录，不清理用户实际 pending ACK）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_ack_receipt.py
```

## 当前限制

- 目前输入仅为模拟 Event，尚未连接真实 Detector。
- ACK 仅支持人工 ACCEPT 生成、人工导入 V2A Receipt 消费；不会修改 V2A 的 `analysis_state` 或 `decision_checkpoint`。
- 目前 DeepSeek 与 OpenAI Provider 可实例化，没有 Provider failover 或 compare mode。
- JSONL 适用于当前小规模实验；未引入数据库，人工 Review/Receipt 消费共用跨进程文件锁。

OpenAI 接入遵循官方 Responses API，并优先通过 `text.format.type=json_schema` 使用 Structured Outputs；仅在 API 明确不支持该格式时执行一次文本 JSON fallback，并在 usage 日志标记。

DeepSeek 接入遵循官方 Responses API，优先使用 JSON Schema Structured Output；仅在该格式明确不支持时回退到 `json_object`，reasoning 正文不会进入 Decision、Handoff 或日志。

官方参考：

- https://developers.openai.com/api/reference/cli/resources/responses/methods/create
- https://developers.openai.com/api/docs/models/gpt-5.4-mini
- https://api-docs.deepseek.com/guides/responses_api/
- https://api-docs.deepseek.com/guides/thinking_mode/
