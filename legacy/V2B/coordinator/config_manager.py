from __future__ import annotations

import importlib.util
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .action_policy import resolve_action_policy
from .errors import CoordinatorError, ErrorCode


DEEPSEEK_REASONING_EFFORTS = {"none", "low", "high", "max"}


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
        resolve_action_policy(data.get("action_policy"))
        return data

    def action_policy(self, mode_override: str | None = None) -> dict[str, Any]:
        return resolve_action_policy(self.data.get("action_policy"), mode_override)

    def resolve_path(self, key: str) -> Path:
        value = self.data.get("paths", {}).get(key)
        if not value:
            raise CoordinatorError(ErrorCode.CONFIG_ERROR, f"paths.{key} is required")
        return (self.project_root / str(value)).resolve()

    def resolve_provider(self, cli_provider: str | None = None, session_provider: str | None = None) -> str:
        name = str(
            cli_provider
            or session_provider
            or self.data.get("ai", {}).get("session_provider")
            or self.data["ai"]["default_provider"]
        ).strip().lower()
        if name not in self.data["ai"]["providers"]:
            raise CoordinatorError(ErrorCode.PROVIDER_NOT_IMPLEMENTED, f"Provider '{name}' is not configured or implemented")
        return name

    def provider_config(self, name: str) -> dict[str, Any]:
        providers = self.data["ai"]["providers"]
        if name not in providers:
            raise CoordinatorError(ErrorCode.PROVIDER_NOT_IMPLEMENTED, f"Provider '{name}' is not configured or implemented")
        config = deepcopy(providers[name] or {})
        if name == "deepseek":
            config.setdefault("reasoning_effort", "none")
            config.setdefault("max_output_tokens", None)
        return config

    def providers_report(self) -> list[dict[str, Any]]:
        from providers import PROVIDER_REGISTRY

        default = self.data["ai"]["default_provider"]
        return [
            {
                "provider": name,
                "enabled": bool(settings.get("enabled")),
                "implemented": name in PROVIDER_REGISTRY,
                "default": name == default,
                "model": settings.get("model") or "",
                "reasoning_effort": (
                    settings.get("reasoning_effort", "none") if name == "deepseek" else None
                ),
                "max_output_tokens": settings.get("max_output_tokens"),
            }
            for name, settings in self.data["ai"]["providers"].items()
        ]

    def doctor(self) -> dict[str, Any]:
        from providers import PROVIDER_REGISTRY

        provider = self.data["ai"]["default_provider"]
        provider_config = self.provider_config(provider)
        provider_implemented = provider in PROVIDER_REGISTRY
        key_env = str(provider_config.get("api_key_env") or "")
        dependencies = {
            name: importlib.util.find_spec(module) is not None
            for name, module in {
                "openai": "openai",
                "PyYAML": "yaml",
                "jsonschema": "jsonschema",
                "python-dotenv": "dotenv",
            }.items()
        }
        return {
            "config": "OK",
            "action_policy": self.action_policy(),
            "default_provider": provider,
            "provider_enabled": bool(provider_config.get("enabled")),
            "provider_implemented": provider_implemented,
            "model_configured": bool(provider_config.get("model")),
            "reasoning_effort": (
                provider_config.get("reasoning_effort", "none") if provider == "deepseek" else None
            ),
            "max_output_tokens": provider_config.get("max_output_tokens"),
            "api_key_env": key_env,
            "api_key_status": "configured" if key_env and os.getenv(key_env) else "missing",
            "dependencies": dependencies,
            "ready": all(dependencies.values())
            and bool(provider_config.get("enabled"))
            and provider_implemented
            and bool(provider_config.get("model"))
            and bool(key_env and os.getenv(key_env)),
        }
