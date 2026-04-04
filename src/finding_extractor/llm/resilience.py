"""Model-composition helpers for fallback and request-concurrency hardening."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import (
    KnownModelName,
    Model,
    ModelRequestParameters,
    StreamedResponse,
    infer_model,
)
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

from finding_extractor.core.config import get_settings
from finding_extractor.llm.model_settings import get_model_settings
from finding_extractor.llm.policy import provider_from_model_id


@dataclass(frozen=True)
class AgentModelRuntime:
    """Resolved runtime model stack and agent-level model settings."""

    model: Model
    model_settings: ModelSettings | None
    model_name: str = ""
    fallback_model_name: str | None = None


class PinnedModelSettingsModel(WrapperModel):
    """Wrapper that always applies one fixed ModelSettings object."""

    def __init__(
        self,
        wrapped: Model | KnownModelName | str,
        pinned_model_settings: ModelSettings | None,
    ) -> None:
        super().__init__(wrapped)
        self._pinned_model_settings = pinned_model_settings

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        _ = model_settings
        return await self.wrapped.request(
            messages,
            self._pinned_model_settings,
            model_request_parameters,
        )

    async def count_tokens(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> RequestUsage:
        _ = model_settings
        return await self.wrapped.count_tokens(
            messages,
            self._pinned_model_settings,
            model_request_parameters,
        )

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        _ = model_settings
        async with self.wrapped.request_stream(
            messages,
            self._pinned_model_settings,
            model_request_parameters,
            run_context,
        ) as response_stream:
            yield response_stream

    def prepare_request(
        self,
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> tuple[ModelSettings | None, ModelRequestParameters]:
        _ = model_settings
        return self.wrapped.prepare_request(self._pinned_model_settings, model_request_parameters)


class ProviderConcurrencyLimitedModel(WrapperModel):
    """Wrapper that serializes model requests through a shared semaphore."""

    def __init__(
        self,
        wrapped: Model | KnownModelName | str,
        limiter: asyncio.Semaphore,
    ) -> None:
        super().__init__(wrapped)
        self._limiter = limiter

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        async with self._limiter:
            return await self.wrapped.request(messages, model_settings, model_request_parameters)

    async def count_tokens(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> RequestUsage:
        async with self._limiter:
            return await self.wrapped.count_tokens(messages, model_settings, model_request_parameters)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        async with self._limiter, self.wrapped.request_stream(
            messages,
            model_settings,
            model_request_parameters,
            run_context,
        ) as response_stream:
            yield response_stream


_PROVIDER_LIMITERS: dict[tuple[str, int], asyncio.Semaphore] = {}


def provider_scope_key(model_name: str) -> str:
    """Return provider scope for shared request limiter keys."""
    provider = provider_from_model_id(model_name)
    if provider is not None:
        return provider
    if ":" in model_name:
        return model_name.split(":", 1)[0]
    return model_name


def get_provider_request_limiter(model_name: str, max_concurrency: int) -> asyncio.Semaphore:
    """Return a process-shared semaphore for a provider scope + concurrency cap."""
    if max_concurrency <= 0:
        raise ValueError("max_concurrency must be >= 1")
    key = (provider_scope_key(model_name), max_concurrency)
    limiter = _PROVIDER_LIMITERS.get(key)
    if limiter is None:
        limiter = asyncio.Semaphore(max_concurrency)
        _PROVIDER_LIMITERS[key] = limiter
    return limiter


def clear_provider_limiters() -> None:
    """Clear in-process provider limiters (test helper)."""
    _PROVIDER_LIMITERS.clear()


def is_timeout_provider_error(exc: Exception) -> bool:
    """Return True when an exception is timeout-shaped across providers."""
    return isinstance(exc, TimeoutError) or type(exc).__name__ == "APITimeoutError"


def is_retryable_provider_error(exc: Exception) -> bool:
    """Return True when provider/model failures are safe to retry/fallback."""
    return isinstance(exc, ModelAPIError) or is_timeout_provider_error(exc)


def should_fallback_on_exception(exc: Exception) -> bool:
    """Return True when fallback should advance to the next configured model."""
    return is_retryable_provider_error(exc)


def _wrap_with_provider_concurrency(
    model: Model | KnownModelName | str,
    *,
    model_name: str,
    max_concurrency: int,
) -> Model:
    if max_concurrency <= 0:
        return infer_model(model)
    limiter = get_provider_request_limiter(model_name, max_concurrency)
    return ProviderConcurrencyLimitedModel(model, limiter=limiter)


def resolve_output_type(
    output_type: Any,
    model_name: str,
    fallback_model_name: str | None = None,
) -> Any:
    """Wrap output_type in NativeOutput if any configured Ollama model needs it.

    When primary and fallback use different output modes (e.g. gpt-oss with tools +
    gemma4 needing native), bias to native — native output works for all models,
    while tool mode doesn't.
    """
    from finding_extractor.llm.model_settings import ollama_needs_native_output

    needs_native = ollama_needs_native_output(model_name)
    if fallback_model_name and not needs_native:
        needs_native = ollama_needs_native_output(fallback_model_name)
    if needs_native:
        from pydantic_ai import NativeOutput

        return NativeOutput(output_type)
    return output_type


def build_resilient_model(
    model_name: str,
    *,
    reasoning: str | None = None,
    fallback_model_name: str | None = None,
    provider_request_max_concurrency: int = 0,
) -> AgentModelRuntime:
    """Build runtime model stack for primary-only or fallback-capable execution."""
    primary_model_settings = get_model_settings(model_name, reasoning)
    primary_model = _wrap_with_provider_concurrency(
        model_name,
        model_name=model_name,
        max_concurrency=provider_request_max_concurrency,
    )
    if fallback_model_name is None:
        return AgentModelRuntime(
            model=primary_model,
            model_settings=primary_model_settings,
            model_name=model_name,
            fallback_model_name=None,
        )

    fallback_model_settings = get_model_settings(fallback_model_name, reasoning)
    fallback_model = _wrap_with_provider_concurrency(
        fallback_model_name,
        model_name=fallback_model_name,
        max_concurrency=provider_request_max_concurrency,
    )
    model_stack = FallbackModel(
        PinnedModelSettingsModel(primary_model, primary_model_settings),
        PinnedModelSettingsModel(fallback_model, fallback_model_settings),
        fallback_on=should_fallback_on_exception,
    )
    return AgentModelRuntime(
        model=model_stack,
        model_settings=None,
        model_name=model_name,
        fallback_model_name=fallback_model_name,
    )


def create_resilient_agent(
    *,
    model_name: str,
    reasoning: str | None,
    instructions: str,
    output_type: Any,
    output_retries: int,
    deps_type: Any | None = None,
) -> Agent[Any, Any]:
    """Create an Agent with shared fallback/concurrency runtime wiring."""
    settings = get_settings()
    fallback = settings.fallback_model
    runtime = build_resilient_model(
        model_name,
        reasoning=reasoning,
        fallback_model_name=fallback,
    )
    resolved_output = resolve_output_type(output_type, model_name, fallback)
    if deps_type is None:
        return Agent(
            runtime.model,
            instructions=instructions,
            output_type=resolved_output,
            output_retries=output_retries,
            model_settings=runtime.model_settings,
        )
    return Agent(
        runtime.model,
        instructions=instructions,
        output_type=resolved_output,
        deps_type=deps_type,
        output_retries=output_retries,
        model_settings=runtime.model_settings,
    )
