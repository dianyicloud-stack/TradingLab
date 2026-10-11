from __future__ import annotations

from typing import Any, Callable

from adapters.ai.errors import CoordinatorError, ErrorCode

from .base import AIProvider


def _build_openai(config: dict[str, Any], *, prompt: str, output_schema: dict[str, Any]) -> AIProvider:
    from .openai_provider import OpenAIProvider

    return OpenAIProvider(config, prompt=prompt, output_schema=output_schema)


def _build_deepseek(config: dict[str, Any], *, prompt: str, output_schema: dict[str, Any]) -> AIProvider:
    from .deepseek_provider import DeepSeekProvider

    return DeepSeekProvider(config, prompt=prompt, output_schema=output_schema)


ProviderBuilder = Callable[..., AIProvider]
PROVIDER_REGISTRY: dict[str, ProviderBuilder] = {
    "openai": _build_openai,
    "deepseek": _build_deepseek,
}


def build_provider(
    name: str,
    config: dict[str, Any],
    *,
    prompt: str,
    output_schema: dict[str, Any],
) -> AIProvider:
    provider_name = str(name).lower()
    provider_builder = PROVIDER_REGISTRY.get(provider_name)
    if provider_builder is None:
        raise CoordinatorError(ErrorCode.PROVIDER_NOT_IMPLEMENTED, f"Provider '{provider_name}' is not implemented")
    if not config.get("enabled"):
        raise CoordinatorError(ErrorCode.PROVIDER_DISABLED, f"Provider '{provider_name}' is disabled")
    return provider_builder(config, prompt=prompt, output_schema=output_schema)


__all__ = ["AIProvider", "PROVIDER_REGISTRY", "build_provider"]
