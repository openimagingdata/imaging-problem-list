"""Optional runtime observability setup via Logfire."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Generator
from contextlib import suppress
from typing import Any, Literal

import structlog

from finding_extractor.core.config import ExtractorSettings, get_settings

logger = structlog.get_logger(__name__)

_lock = threading.Lock()
_configured = False
_instrumented: set[str] = set()


def get_current_trace_id() -> str | None:
    """Return the current OpenTelemetry trace ID as a hex string, or None."""
    try:
        from opentelemetry import trace
    except Exception:
        return None

    with suppress(Exception):
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            return f"{ctx.trace_id:032x}"
    return None


def _coerce_send_mode(value: bool | str) -> bool | Literal["if-token-present"]:
    if isinstance(value, bool):
        return value
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return "if-token-present"


def _instrument_once(name: str, fn: Any, *args: Any, **kwargs: Any) -> None:
    if name in _instrumented:
        return
    try:
        fn(*args, **kwargs)
    except RuntimeError as exc:
        # Optional instrumentation packages may be absent in some runtimes.
        logger.warning(
            "Logfire instrumentation unavailable",
            instrumentation=name,
            error=str(exc),
        )
    except Exception:
        logger.exception(
            "Failed to initialize Logfire instrumentation",
            instrumentation=name,
        )
    else:
        _instrumented.add(name)


def configure_logfire(
    *,
    runtime: Literal["cli", "api", "worker", "other"] = "other",
    enabled_override: bool | None = None,
    fastapi_app: Any | None = None,
) -> bool:
    """Configure Logfire once per process and apply relevant instrumenters.

    Returns True when logfire is enabled and configured for this process.
    """
    settings = get_settings()

    # Hard short-circuit under local-only mode, regardless of enabled_override.
    # Layer 1 already force-disables logfire_enabled/logfire_token at settings
    # load; this second check protects against any future code path that
    # passes enabled_override=True.
    if settings.local_only_mode:
        if enabled_override:
            logger.warning(
                "Logfire enable request ignored under local-only mode",
                runtime=runtime,
            )
        return False

    enabled = settings.logfire_enabled if enabled_override is None else enabled_override
    if not enabled:
        return False

    try:
        import logfire
    except Exception:
        logger.exception("Logfire requested but package import failed")
        return False

    global _configured
    with _lock:
        if not _configured:
            configure_kwargs: dict[str, Any] = {
                "send_to_logfire": _coerce_send_mode(settings.logfire_send),
                "service_name": settings.logfire_service_name,
                "environment": settings.logfire_environment,
            }
            if settings.logfire_token:
                configure_kwargs["token"] = settings.logfire_token
            logfire.configure(**configure_kwargs)
            _configured = True
            logger.info("Logfire enabled", runtime=runtime)

        _instrument_core(logfire, settings)
        if fastapi_app is not None:
            _instrument_fastapi(logfire, settings, fastapi_app)

    return True


def _instrument_core(logfire: Any, settings: ExtractorSettings) -> None:
    _instrument_once("pydantic_ai", logfire.instrument_pydantic_ai)
    _instrument_once(
        "httpx",
        logfire.instrument_httpx,
        capture_headers=settings.logfire_capture_headers,
    )
    _instrument_once("sqlalchemy", logfire.instrument_sqlalchemy)

    if settings.logfire_instrument_provider_sdks:
        _instrument_once("openai_sdk", logfire.instrument_openai)
        _instrument_once("anthropic_sdk", logfire.instrument_anthropic)
        if hasattr(logfire, "instrument_google_genai"):
            _instrument_once("google_genai_sdk", logfire.instrument_google_genai)

    if settings.logfire_system_metrics:
        _instrument_once("system_metrics", logfire.instrument_system_metrics)


def _instrument_fastapi(logfire: Any, settings: ExtractorSettings, app: Any) -> None:
    name = f"fastapi:{id(app)}"
    _instrument_once(
        name,
        logfire.instrument_fastapi,
        app,
        capture_headers=settings.logfire_capture_headers,
        excluded_urls="/api/healthz,/api/readyz",
    )


# ---------------------------------------------------------------------------
# Lightweight span helper for orchestration-level observability
# ---------------------------------------------------------------------------


class SpanHandle:
    """Thin wrapper exposing ``set_attribute`` on a Logfire/OTEL span."""

    __slots__ = ("_span",)

    def __init__(self, span: Any) -> None:
        self._span = span

    def set_attribute(self, key: str, value: Any) -> None:
        self._span.set_attribute(key, value)


class _NoopHandle(SpanHandle):
    """Silent no-op when Logfire is unavailable."""

    __slots__ = ()

    def __init__(self) -> None:
        pass  # no underlying span

    def set_attribute(self, key: str, value: Any) -> None:
        pass


_NOOP_HANDLE = _NoopHandle()


@contextlib.contextmanager
def observation_span(name: str, **attributes: Any) -> Generator[SpanHandle]:
    """Create a Logfire span if available, otherwise no-op.

    Usage::

        with observation_span("extraction.chunk", chunk_id=cid) as span:
            result = await do_work()
            span.set_attribute("findings_count", len(result.findings))
    """
    if not _configured:
        yield _NOOP_HANDLE
        return

    try:
        import logfire
    except Exception:
        yield _NOOP_HANDLE
        return

    with logfire.span(name, **attributes) as span:
        yield SpanHandle(span)
