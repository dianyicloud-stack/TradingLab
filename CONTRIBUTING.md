# Contributing

TradingLab accepts focused pull requests against `main`. Please keep a change limited to the behavior it claims to change.

简体中文：欢迎针对 `main` 的小范围拉取请求。请同步更新 `README.md` 与 `README.zh-CN.md`。不要提交密钥、聊天 ID、账户数据或数据库。不要修改 `legacy/`。

## Privacy

Do not commit `.env`, `.env.telegram`, API keys, bot tokens, chat IDs, account ledgers, or market databases. Runtime directories such as `data/`, `.dev/`, `.venv/`, `logs/`, and `artifacts/` are local. `.gitignore` already excludes them.

## Frozen reference

`legacy/` is a read-only tree. `python trading_lab.py --verify-baselines` hashes it against `docs/frozen_baselines.json` and returns exit code 1 when anything differs.

`portable-work/source-lock.json` records hashes for many tracked files, including `README.md`. Editing a locked file makes that lock disagree with the worktree. Update the lock only in a change whose purpose is to publish a new lock.

## Checks

From the repository root, using the same interpreter that runs the app:

```bash
python -m unittest discover -s tests -v
python trading_lab.py --verify-baselines
```

`unittest discover -s tests` does not collect tests under `legacy/`.

## Style

Match the file you are editing. The web UI copy is Simplified Chinese. Public project docs are English in `README.md` and Simplified Chinese in `README.zh-CN.md`; update both when behavior changes.

## License

By submitting a contribution you agree that it is licensed under the MIT License in `LICENSE`.
