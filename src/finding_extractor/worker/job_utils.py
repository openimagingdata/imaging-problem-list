"""Shared helpers for TaskIQ background job modules."""

from __future__ import annotations

from typing import Annotated

from fastapi import Request
from pydantic_ai.exceptions import FallbackExceptionGroup, ModelAPIError, UnexpectedModelBehavior
from taskiq import TaskiqDepends

from finding_extractor.db.store import ExtractionStore
from finding_extractor.llm.resilience import is_retryable_provider_error, is_timeout_provider_error


def get_task_store(request: Annotated[Request, TaskiqDepends()]) -> ExtractionStore:
    """Task dependency that retrieves store from FastAPI app state."""
    return request.app.state.store


def flatten_exception_group(exc_group: BaseExceptionGroup[BaseException]) -> list[Exception]:
    """Flatten nested exception groups into ordinary Exception instances."""
    flattened: list[Exception] = []
    for nested in exc_group.exceptions:
        if isinstance(nested, BaseExceptionGroup):
            flattened.extend(flatten_exception_group(nested))
        elif isinstance(nested, Exception):
            flattened.append(nested)
    return flattened


def to_public_job_error(exc: Exception, *, job_name: str) -> str:
    """Return a stable, non-sensitive public error string for a background job."""
    if isinstance(exc, ValueError):
        return f"{job_name}_failed:invalid_request"
    if isinstance(exc, FallbackExceptionGroup):
        fallback_errors = flatten_exception_group(exc)
        if fallback_errors and all(is_timeout_provider_error(error) for error in fallback_errors):
            return f"{job_name}_failed:model_timeout"
        if fallback_errors and all(is_retryable_provider_error(error) for error in fallback_errors):
            return f"{job_name}_failed:model_provider_error"
    if isinstance(exc, ModelAPIError):
        return f"{job_name}_failed:model_provider_error"
    if isinstance(exc, UnexpectedModelBehavior):
        return f"{job_name}_failed:model_output_validation_failed"
    if is_timeout_provider_error(exc):
        return f"{job_name}_failed:model_timeout"
    return f"{job_name}_failed:internal_error"
