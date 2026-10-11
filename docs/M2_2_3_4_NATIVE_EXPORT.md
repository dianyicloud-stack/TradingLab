# M2.2.3.4 Native Export & Live Synchronization

## Scope and source audit

LIVE owns native export, ingestion runtime and factual copies. V2A remains the sole writer of source sessions, observations, events and confirmed cursors. Decisions retains immutable opinions. Account writes only through its existing Port. No frozen protocol, Account Engine, M3 or Daily Market Review changes.

The accepted source is `legacy/v2a/量价查询_V2A.1.2.2_Decision_ACK导入版.html`, SHA256 `fd155f387747551a603b21ac0f54e7618ef3e47f95bf5ab0b2bc13043441f2ae`. Reading source establishes its behavior, not which browser file the user currently has open. Browser inventory was unavailable; the active source page/origin remains unverified. Historical NOT_FOUND requests cannot be uniquely attributed without their original URL/log.

The native five-minute chain is `startTracker → captureTracker → captureOneTracker → buildTrackerRow → session.rows → saveTrackerStore`. `tracker.store.sessions` is serialized to localStorage key `sina_stock_auto_tracker_v1`. `backfillTrackerMetrics`, `backfillTrackerBoardChanges` and `retryMissingBoardBreadths` may revise an existing row. `trackerRowsWithEventDetails` computes the existing native display/export metrics from those native rows.

The optional per-stock CSV writer requires each stock's `csvEnabled`, a separately selected file and browser permission. It includes session ID and native derived metrics, with numeric rounding, and appends successful newly captured rows. It is not a versioned revision export and does not reliably publish every subsequent native revision. In the audited configured Workspace, there was no complete observations export or market_raw.csv. The enhanced outlet preserves raw precision, native stored payload and subsequent revisions; it is not justified by pretending the existing CSV lacks session identity.

The independent quick chain is `startRealtimeMonitor → runRealtimeSample → runtimeState buffer`; five-second sampling, thirty-second market_raw.csv append, ten-second runtime_state.json overwrite. It does not publish the complete five-minute observation row. An open page, five-minute tracker, quick monitor, directory binding and successful export are different states.

The native event engine scans tracker rows and runtime samples separately and writes its own events.jsonl. Selecting/restoring the original runtime directory activates its native restore/write behavior. Quick monitor start/stop does not itself start/stop the five-minute tracker. Closing the browser stops browser tasks; daily reset/pruning can remove browser-retained history. The exporter cannot recover rows V2A no longer retains. Existing Workspace events and analysis state alone cannot prove sampling is running.

## Export-enhanced copy

Entry: `integrations/v2a/V2A_Native_Export_1.0.0.html`. Its companion manifest records source and copy hashes. `tools/build_v2a_export.py` inserts an asynchronous notification in `saveTrackerStore`, plus a standalone exporter/status panel. Removing those insertions reconstructs the authoritative source bytes exactly. No native algorithms or protocol blocks are replaced. The export snapshot reuses `trackerRowsWithEventDetails`; `stored_payload` preserves the original stored row inside the enriched raw payload.

The default namespace is `exports/trading_lab/v1`. Backend configuration is `TRADING_LAB_V2A_EXPORT_NAMESPACE`; rebuild the copy with `--namespace` to use another relative namespace. The Workspace root remains solely `TRADING_LAB_V2A_WORKSPACE` in the backend and a user-authorized directory handle in the browser. No business code contains the Windows deployment path.

Files:

| File | Meaning |
|---|---|
| sessions.json | Native session identity, symbol, name, day, lifecycle, export capability |
| observations.jsonl | Appended native row versions, raw payload, identity, times, units and missing reasons |
| publication.json | Successfully closed row versions and their successful export timestamps |
| status.json | Exporter version/publisher, queue, heartbeat, error, separate tracker and quick-monitor states |
| publisher.lock | Browser exclusive writer held for the publisher lifetime |

No second event ledger is introduced. Trading Lab still reads the native root events.jsonl. The enhancement never writes analysis_state, checkpoint, Handoff, ACK or Receipt. Selecting the native runtime directory remains the existing V2A operation.

Writes are serialized. Browser Web Locks and an exclusive FileSystem writable prevent competing publishers. Failed writes do not advance publication or idempotency. Retry uses the retained native row. A startup-corrupt export journal is preserved and reported, not truncated. Initial retained rows are BACKFILL; revisions keep observation identity and original market interval. Live establishes a persistent backfill baseline, including the observation cutoff, to avoid treating delayed historical event publication as a new automatic trigger.

The reader requires a successful publication marker, valid session/stock/day, matching raw hash and record identity. Incomplete tails are retried. Complete corrupt records are isolated with line/hash diagnostics; publication gaps and size-limit failures are explicit. Native event gaps do not jump the cursor to the source maximum. This contiguous-log rule does not apply to the older bounded snapshot Contract.

## Time and AI correctness

`market_observed_at`, native interval end, event time, original capture time, revision availability, export attempt, successful exported_at and first ingested_at are separate. Missing source timestamps remain unknown. Revisions use the exporter observation time as a conservative availability boundary. Read-only heartbeats do not become market observations.

Live reports observation/quote-based market age, separate event age, published-versus-read backlog and export-to-first-ingest time. It does not call event age transport latency. Five-minute observations use a five-minute cadence plus the exported grace interval. The existing calendar is injected as a read-only callback; clock and timestamps are Shanghai-aware. Lunch, close-complete, close-tail-missing, pre-open, no first data, non-trading day and unknown calendar are distinct. Stale exporter heartbeats mean UNKNOWN, not proof that the source stopped.

The existing per-symbol queue/provider/opinion repository remains in place. Full native observations and quick samples remain separately tagged. Partial/event-only evidence can support explicit limited manual analysis; automatic full analysis and account execution are blocked when required full evidence is missing. Account errors are visible but do not remove facts or stop market opinions; execution is blocked. No production execution settings are reset.

The Engine checks source times throughout the frozen market payload, native metrics and nested observations/events. A future or unproven timestamp is rejected. Previous opinion selection checks symbol/session/mode, provenance qualification and market cutoff. Old contaminated opinions remain immutable and visible in history; a separate provenance audit records their eligibility when a new result is saved. They are not rewritten or silently trusted as context.

Runtime migrations add `native_control` and `advisory_provenance_audit` with idempotent CREATE TABLE. Existing settings, opinions, account and learning facts are preserved. Native row revisions have distinct ingestion identities and successful-advice record tracking. The data-root process lease remains acquired before migrations; another port cannot bypass it.

## UI and startup

Live keeps per-stock events, current observation/time, independent AI controls/opinion and account summary. Source errors preserve the last successful page contents and mark them non-current. Account errors show unknown account state, not a zero position. Hidden stocks with AI enabled produce a visible notice. Model reasoning choices come from the registry's capability declaration; the frontend does not invent model names. The frontend checks the running service build identity, and the service pins its JS bytes for the process lifetime.

Formal protocol data stays in Decisions → advanced protocol audit. No Formal records are deleted. Provider, model, preferences and native browser directory handles retain their existing persistence mechanisms.

First switch is manual. Keep the old V2A page and its browser storage intact. A different HTML path/origin or browser profile can have different localStorage and IndexedDB; the enhanced copy must not be assumed to contain today's existing rows or the same session counters. Do not run both source pages against the same native Workspace. For a clean first deployment, switch on a new trading day after stopping the old page's tracking and quick monitoring; alternatively first establish a separately verified same-origin storage handoff. No silent storage migration is supplied.

Open only the enhanced entry above in the chosen browser/profile. Use V2A's original “选择运行目录” to bind the configured Workspace, then “选择 Workspace 并启用导出”; the latter reuses the original bound directory. Start the original five-minute tracker. Quick sampling remains optional and separate. Saved export permission is restored when valid; explicitly pausing export remains paused after reload. If permission expires, reselect through the native directory control. On later days use the same enhanced file/profile and restored directory, start native tracking, and use the formal Trading Lab URL `http://127.0.0.1:8765/live`.

Real AI acceptance requires explicit permission for at most one manual and one automatic call, after checking account execution isolation. No ACCEPT, Import ACK or Formal receipt consumption belongs to this acceptance.

## Evidence and rollback

`artifacts/m2234/before.json` records the opening inventory and source hashes. `code-before` is a code backup; `sqlite-before` contains SQLite backup-API snapshots with integrity checks, versions and table counts. These database backups are forensic/recovery evidence, not a routine rollback instruction. Do not restore them over new business facts.

Stop only the identified Trading Lab process before code rollback; restore the changed code paths from `code-before`, retain data and added runtime tables, and keep the enhanced publisher paused. Original Legacy and its hashes never need restoration because they were not edited. Returning to an original source browser requires the same storage/session precautions as first switching.

Browser integration executes the actual enhanced HTML, native row builder/commit and exporter in an isolated Chromium profile. Chromium OPFS supplies the real FileSystem API. The harness mirrors successfully produced file bytes into a TEST Workspace; Python does not manufacture those native observation rows. It also exercises native event generation, revision, restart, competing publisher and permission faults. This verifies the export code, not the user's physical-directory permission prompt or current browser storage.

All final acceptance statuses, protected-file comparisons and current production observations are in `artifacts/m2234/acceptance.json`. Real new events and two consecutive real native observations must remain PENDING until actually observed. A passing isolated browser test is not a real market acceptance.

Current limits: the reader explicitly stops at its 20 MB per-file limit; no automatic journal rotation or destructive repair is introduced. The isolated browser uses OPFS, so the user's physical Windows-directory permission and file-origin storage continuity remain separate manual acceptance items. Retained browser history is the only backfill source; missing historical rows cannot be regenerated by this exporter.
