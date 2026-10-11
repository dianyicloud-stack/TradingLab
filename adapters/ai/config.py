from __future__ import annotations
from typing import Any
from pathlib import Path
from copy import deepcopy
import yaml
from dotenv import load_dotenv
from adapters.ai.errors import CoordinatorError, ErrorCode
DEEPSEEK_REASONING_EFFORTS={"none","low","high","max"}

class ConfigManager:
    def __init__(self, project_root: Path, config_path: Path | None = None) -> None:
        self.project_root = Path(project_root).resolve()
        self.config_path = Path(config_path or self.project_root / "config.yaml").resolve()
        load_dotenv(self.project_root / ".env", override=False)
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError as error:
            raise CoordinatorError(ErrorCode.CONFIG_ERROR, f"Config not found: {self.config_path}") from error
        except yaml.YAMLError as error:
            raise CoordinatorError(ErrorCode.CONFIG_ERROR, f"Invalid YAML: {error}") from error
        providers = data.get("ai", {}).get("providers")
        default = data.get("ai", {}).get("default_provider")
        if not isinstance(providers, dict) or not providers:
            raise CoordinatorError(ErrorCode.CONFIG_ERROR, "ai.providers must be a non-empty mapping")
        if not isinstance(default, str) or default not in providers:
            raise CoordinatorError(ErrorCode.CONFIG_ERROR, "ai.default_provider must name a configured provider")
        deepseek = providers.get("deepseek") or {}
        reasoning_effort = deepseek.get("reasoning_effort", "none")
        if reasoning_effort not in DEEPSEEK_REASONING_EFFORTS:
            allowed = ", ".join(sorted(DEEPSEEK_REASONING_EFFORTS))
            raise CoordinatorError(
                ErrorCode.CONFIG_ERROR,
                f"ai.providers.deepseek.reasoning_effort must be one of: {allowed}",
            )
        max_output_tokens = deepseek.get("max_output_tokens")
        if max_output_tokens is not None and (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or max_output_tokens <= 0
        ):
            raise CoordinatorError(
                ErrorCode.CONFIG_ERROR,
                "ai.providers.deepseek.max_output_tokens must be null or a positive integer",
            )
        return data

    def provider_config(self, name: str) -> dict[str, Any]:
        providers = self.data["ai"]["providers"]
        if name not in providers:
            raise CoordinatorError(ErrorCode.PROVIDER_NOT_IMPLEMENTED, f"Provider '{name}' is not configured or implemented")
        config = deepcopy(providers[name] or {})
        if name == "deepseek":
            config.setdefault("reasoning_effort", "none")
            config.setdefault("max_output_tokens", None)
        return config
