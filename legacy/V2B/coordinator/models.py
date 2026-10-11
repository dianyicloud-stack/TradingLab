from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")
JOB_STATUSES = ("QUEUED", "RUNNING", "RESULT_READY", "FAILED")
DECISION_ACTIONS = ("HOLD", "WATCH", "EXIT", "NO_ACTION")


def now_iso() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def timestamp_id(prefix: str, suffix_length: int) -> str:
    now = datetime.now(SHANGHAI)
    suffix = uuid4().hex[:suffix_length].upper()
    return f"{prefix}-{now:%Y%m%d-%H%M%S}-{suffix}"


def new_job_id() -> str:
    return timestamp_id("JOB", 6)


def new_decision_id() -> str:
    return timestamp_id("DEC", 6)


def new_handoff_id() -> str:
    return timestamp_id("EHO", 4)


def json_size_bytes(value: Any) -> int:
    import json

    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
