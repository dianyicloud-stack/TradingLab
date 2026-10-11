"""Frozen-file verification. The manifest is the versioned authority."""
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify_baselines(project_root: Path) -> dict:
    manifest = json.loads((project_root / "docs/frozen_baselines.json").read_text(encoding="utf-8-sig"))
    legacy_root = (project_root / "legacy").resolve()
    expected = {entry["path"]: entry for entry in manifest["files"]}
    actual = {path.relative_to(project_root).as_posix(): path for path in legacy_root.rglob("*") if path.is_file()}
    changes = []
    for relative, entry in expected.items():
        path = project_root / relative
        if not path.resolve().is_relative_to(legacy_root):
            changes.append({"path": relative, "status": "UNSAFE_PATH"})
            continue
        current = sha256(path) if path.is_file() else None
        if current != entry["sha256"]:
            changes.append({"path": relative, "status": "MISSING" if current is None else "CHANGED", "actual": current})
    changes.extend({"path": relative, "status": "ADDED"} for relative in sorted(set(actual) - set(expected)))

    authoritative_checks = []
    for baseline in manifest.get("authoritative_baselines", []):
        relative = baseline.get("path", "")
        path = project_root / relative
        configured_hash = baseline.get("sha256")
        manifest_hash = expected.get(relative, {}).get("sha256")
        if not relative or not path.resolve().is_relative_to(legacy_root):
            actual_hash = None
            check_status = "UNSAFE_PATH"
        elif configured_hash != manifest_hash:
            actual_hash = sha256(path) if path.is_file() else None
            check_status = "MANIFEST_CONFLICT"
        else:
            actual_hash = sha256(path) if path.is_file() else None
            check_status = "PASS" if actual_hash == configured_hash else "MISSING" if actual_hash is None else "MISMATCH"
        authoritative_checks.append({
            "version": baseline.get("version"), "path": relative,
            "baseline_status": baseline.get("status"), "expected": configured_hash,
            "actual": actual_hash, "status": check_status,
        })

    unchanged = not changes
    authoritative_pass = bool(authoritative_checks) and all(item["status"] == "PASS" for item in authoritative_checks)
    status = "READY" if unchanged and authoritative_pass else "ERROR"
    return {
        "manifest_version": manifest.get("manifest_version"), "captured_at": manifest["captured_at"],
        "finalized_on": manifest.get("finalized_on"), "file_count": len(expected), "unchanged": unchanged,
        "frozen_baselines": "PASS" if authoritative_pass else "FAIL",
        "authoritative_checks": authoritative_checks,
        "historical_references": manifest.get("historical_references", []),
        "changes": changes, "status": status,
    }
