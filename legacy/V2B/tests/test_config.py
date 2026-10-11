from __future__ import annotations

import os

import pytest

from coordinator.config_manager import ConfigManager
from coordinator.errors import CoordinatorError, ErrorCode
from providers import build_provider
from providers.openai_provider import OpenAIProvider


def test_t01_normal_config_read(sandbox_project):
    config = ConfigManager(sandbox_project)
    assert config.resolve_provider() == "deepseek"
    assert config.provider_config("deepseek")["model"] == "deepseek-v4-pro"
    assert config.provider_config("openai")["model"] == "gpt-5.4-mini"
    assert config.resolve_path("decisions") == sandbox_project / "state" / "decisions.jsonl"
    assert config.provider_config("deepseek")["reasoning_effort"] == "none"
    assert config.provider_config("deepseek")["max_output_tokens"] is None
    assert config.doctor()["reasoning_effort"] == "none"
    assert config.doctor()["max_output_tokens"] is None


def test_t02_missing_openai_api_key(sandbox_project, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = ConfigManager(sandbox_project).provider_config("openai")
    with pytest.raises(CoordinatorError) as caught:
        OpenAIProvider(config, prompt="test", output_schema={"type": "object"})
    assert caught.value.code == ErrorCode.API_KEY_MISSING
    assert "sk-" not in caught.value.message


def test_t03_unknown_provider(sandbox_project):
    config = ConfigManager(sandbox_project)
    with pytest.raises(CoordinatorError) as caught:
        config.resolve_provider("unknown-provider")
    assert caught.value.code == ErrorCode.PROVIDER_NOT_IMPLEMENTED


def test_t04_disabled_provider(sandbox_project):
    config = ConfigManager(sandbox_project).provider_config("openai")
    config["enabled"] = False
    with pytest.raises(CoordinatorError) as caught:
        build_provider("openai", config, prompt="test", output_schema={"type": "object"})
    assert caught.value.code == ErrorCode.PROVIDER_DISABLED


def test_provider_selection_priority(sandbox_project):
    config = ConfigManager(sandbox_project)
    assert config.resolve_provider("openai", "qwen") == "openai"
    assert config.resolve_provider(None, "qwen") == "qwen"


def test_invalid_deepseek_reasoning_effort_is_config_error(sandbox_project):
    path = sandbox_project / "config.yaml"
    text = path.read_text(encoding="utf-8").replace(
        "reasoning_effort: none",
        "reasoning_effort: medium",
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(CoordinatorError) as caught:
        ConfigManager(sandbox_project)

    assert caught.value.code == ErrorCode.CONFIG_ERROR
    assert "reasoning_effort" in caught.value.message


def test_deepseek_provider_report_includes_reasoning_and_provider_default_tokens(sandbox_project):
    report = {
        item["provider"]: item
        for item in ConfigManager(sandbox_project).providers_report()
    }
    assert report["deepseek"]["reasoning_effort"] == "none"
    assert report["deepseek"]["max_output_tokens"] is None
