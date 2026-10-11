"""Explicit external diagnostic through the frozen legacy provider; no Decision jobs."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from adapters.baselines import verify_baselines
from shared.config import ScopedStore


def main():
    result = {"provider": "deepseek", "model": "unknown", "status": "PROVIDER_ERROR", "latency_ms": 0,
              "timestamp": datetime.now(timezone.utc).isoformat()}
    if not verify_baselines(ROOT)["unchanged"]:
        result["status"] = "LEGACY_BASELINE_FAILED"
    else:
        try:
            with tempfile.TemporaryDirectory(prefix="tradinglab-provider-") as temporary:
                run = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "adapters/legacy_v2b/smoke_worker.py"), str(ROOT)],
                                     cwd=temporary, capture_output=True, timeout=300, encoding="utf-8")
            # Never relay stdout/stderr on failure. Accept exactly the diagnostic allowlist.
            data = json.loads(run.stdout)
            allowed = {"READY", "CONFIG_ERROR", "API_KEY_MISSING", "AUTH_FAILED", "RATE_LIMITED", "TIMEOUT", "PROVIDER_ERROR",
                       "EMPTY_PROVIDER_RESPONSE", "INVALID_RESPONSE", "SCHEMA_VALIDATION_FAILED", "MODEL_INVALID", "PROVIDER_DISABLED"}
            if (run.returncode == 0 and set(data) == set(result) and data["provider"] == "deepseek" and
                re.fullmatch(r"(?:unknown|deepseek-[a-zA-Z0-9._-]{1,60})", data["model"]) and data["status"] in allowed and
                type(data["latency_ms"]) is int and 0 <= data["latency_ms"] <= 300_000):
                datetime.fromisoformat(data["timestamp"])
                result = data
        except subprocess.TimeoutExpired:
            result["status"] = "TIMEOUT"
        except Exception:
            pass
        if not verify_baselines(ROOT)["unchanged"]:
            result["status"] = "LEGACY_BASELINE_FAILED"
    store = ScopedStore(ROOT / "data/decisions", boundary=ROOT)
    store.ensure()
    store.write_text("provider_smoke.json", json.dumps(result))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "READY" else 1


if __name__ == "__main__":
    sys.exit(main())
