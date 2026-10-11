"""Environment-independent settings and constrained filesystem capabilities."""
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


@dataclass(frozen=True)
class Settings:
    project_root: Path
    port: int = 8765
    data_root: Path | None = None
    source: str = "USER"
    test_run_id: str | None = None

    def __post_init__(self):
        project_root = self.project_root.resolve()
        object.__setattr__(self, "project_root", project_root)
        data_root = (self.data_root or project_root / "data").resolve()
        if not data_root.is_relative_to(project_root):
            raise ValueError("Data root must remain inside the project root")
        object.__setattr__(self, "data_root", data_root)
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if self.source not in {"USER", "TEST"}:
            raise ValueError("source must be USER or TEST")
        if self.source == "TEST" and not self.test_run_id:
            raise ValueError("TEST runs require a test_run_id")
        if self.source == "USER" and self.test_run_id is not None:
            raise ValueError("USER runs cannot carry a test_run_id")


class ScopedStore:
    """Prevents accidental path escapes; not a sandbox for hostile Python code."""

    def __init__(self, root: Path, *, boundary: Path):
        self._root = root.absolute()
        self._boundary = boundary.resolve()
        self.path()

    def path(self, relative: str = "") -> Path:
        if not isinstance(relative, str):
            raise ValueError("Use a relative string path")
        portable = relative.replace("\\", "/")
        windows = PureWindowsPath(relative)
        if windows.drive or windows.root or ":" in relative or "\x00" in relative:
            raise ValueError("Absolute, drive, UNC and ADS paths are forbidden")
        if any(part in {"..", "."} or part.rstrip(" .") != part for part in portable.split("/") if part):
            raise ValueError("Traversal and ambiguous Windows paths are forbidden")
        root = self._root.resolve()
        if root != self._root or not root.is_relative_to(self._boundary):
            raise ValueError("Store escaped its permitted boundary")
        result = (self._root / portable).resolve()
        if not result.is_relative_to(root):
            raise ValueError("Path escaped its domain store")
        return result

    def ensure(self):
        self.path().mkdir(parents=True, exist_ok=True)

    def child(self, relative: str):
        return ScopedStore(self.path(relative), boundary=self.path())

    def write_text(self, relative: str, content: str):
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target = self.path(relative)
        target.write_text(content, encoding="utf-8")
