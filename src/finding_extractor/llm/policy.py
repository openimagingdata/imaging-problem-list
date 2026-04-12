"""Shared model ID policy and parsing helpers.

This module is the canonical source for:
- Provider detection from model ID prefixes
- Model ID validation and equivalence checking
- SOTA (state-of-the-art) model filtering for discovery

Provider-specific settings configuration lives in `providers.py`, which imports
detection logic from this module to avoid duplication.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable, Sequence
from urllib.parse import urlparse

OPENAI_SKIP_TOKENS = (
    "audio",
    "embed",
    "embedding",
    "image",
    "moderation",
    "omni",
    "realtime",
    "search",
    "transcribe",
    "tts",
    "whisper",
)
ANTHROPIC_ALLOWED_MAJOR = 4
ANTHROPIC_ALLOWED_MINORS = {5, 6}
GOOGLE_ALLOWED_MAJOR = 3
GOOGLE_ALLOWED_TIERS = {"pro", "flash"}

ANTHROPIC_RE_A = re.compile(
    r"^claude-(?P<tier>opus|sonnet|haiku)-(?P<major>\d+)-(?P<minor>\d+)(?:-(?P<stamp>\d{8}))?$"
)
ANTHROPIC_RE_B = re.compile(
    r"^claude-(?P<major>\d+)-(?P<minor>\d+)-(?P<tier>opus|sonnet|haiku)(?:-(?P<stamp>\d{8}))?$"
)
GOOGLE_RE = re.compile(
    r"^gemini-(?P<major>\d+)(?:\.(?P<minor>\d+))?-(?P<tier>pro|flash)(?:-(?P<suffix>[a-z0-9.-]+))?$"
)
OPENAI_RE = re.compile(
    r"^gpt-(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:-(?P<tier>mini|nano))?(?:-(?P<suffix>[a-z0-9.-]+))?$"
)

KNOWN_PROVIDER_PREFIXES = {
    "openai",
    "openai-chat",
    "openai-responses",
    "anthropic",
    "google-gla",
    "openrouter",
    "ollama",
}

# Canonical provider prefix mapping (normalized provider names)
# Used by both model_policy.py (validation) and providers.py (runtime settings)
PROVIDER_PREFIX_MAP = {
    "openai": "openai",
    "openai-chat": "openai",
    "openai-responses": "openai",
    "anthropic": "anthropic",
    "google-gla": "google",
    "openrouter": "openrouter",
    "ollama": "ollama",
}


ModelScore = tuple[int, int, int, int]
ModelParser = Callable[[str], tuple[str, ModelScore] | None]


def provider_from_model_id(model_id: str) -> str | None:
    """Return normalized provider name for known model prefixes."""
    if ":" not in model_id:
        return None
    prefix = model_id.split(":", maxsplit=1)[0]
    return PROVIDER_PREFIX_MAP.get(prefix)


def canonical_model_key(model_id: str) -> tuple[str, str] | None:
    """Return `(provider, raw_model_id)` with provider aliases normalized."""
    provider = provider_from_model_id(model_id)
    if provider is None or ":" not in model_id:
        return None
    _, raw_model_id = model_id.split(":", maxsplit=1)
    return provider, raw_model_id


def model_ids_equivalent(lhs: str, rhs: str) -> bool:
    """Compare model IDs with provider-alias normalization."""
    lhs_key = canonical_model_key(lhs)
    rhs_key = canonical_model_key(rhs)
    if lhs_key is None or rhs_key is None:
        return lhs == rhs
    return lhs_key == rhs_key


def output_model_prefix(provider: str) -> str:
    """Choose output prefix for provider model IDs."""
    if provider != "google":
        return provider
    return "google-gla"


def _suffix_stamp_rank(suffix: str | None) -> int:
    if not suffix:
        return 0
    digits = suffix.replace("-", "")
    if len(digits) == 8 and digits.isdigit():
        return int(digits)
    return 0


def _pick_latest_by_tier(
    model_ids: set[str],
    parser: ModelParser,
) -> list[tuple[str, str]]:
    chosen: dict[str, tuple[ModelScore, str]] = {}
    for model_id in sorted(model_ids):
        parsed = parser(model_id)
        if parsed is None:
            continue
        tier, score = parsed
        current = chosen.get(tier)
        if current is None:
            chosen[tier] = (score, model_id)
            continue
        current_score, current_model_id = current
        if score > current_score or (score == current_score and model_id > current_model_id):
            chosen[tier] = (score, model_id)
    return [(tier, model_id) for tier, (_, model_id) in chosen.items()]


def _parse_openai(model_id: str) -> tuple[str, ModelScore] | None:
    lowered = model_id.lower()
    if not lowered.startswith("gpt-"):
        return None
    if any(token in lowered for token in OPENAI_SKIP_TOKENS):
        return None
    match = OPENAI_RE.match(lowered)
    if match is None:
        return None
    tier = match.group("tier") or "base"
    major = int(match.group("major"))
    minor = int(match.group("minor") or "0")
    suffix = match.group("suffix")
    stable_rank = 1 if suffix is None else 0
    return tier, (major, minor, stable_rank, _suffix_stamp_rank(suffix))


def anthropic_model_minor(model_id: str) -> int | None:
    """Return the minor version from an Anthropic model ID, or None if unparseable.

    Accepts both prefixed ("anthropic:claude-opus-4-6") and bare ("claude-opus-4-6") IDs.
    """
    raw = model_id.split(":", maxsplit=1)[-1].lower()
    match = ANTHROPIC_RE_A.match(raw) or ANTHROPIC_RE_B.match(raw)
    if match is None:
        return None
    return int(match.group("minor"))


def _parse_anthropic(model_id: str) -> tuple[str, ModelScore] | None:
    lowered = model_id.lower()
    if not lowered.startswith("claude-"):
        return None
    match = ANTHROPIC_RE_A.match(lowered) or ANTHROPIC_RE_B.match(lowered)
    if match is None:
        return None
    tier = match.group("tier")
    major = int(match.group("major"))
    minor = int(match.group("minor"))
    if major != ANTHROPIC_ALLOWED_MAJOR or minor not in ANTHROPIC_ALLOWED_MINORS:
        return None
    stamp = match.group("stamp")
    stable_rank = 1 if stamp is None else 0
    return tier, (major, minor, stable_rank, _suffix_stamp_rank(stamp))


def _parse_google(model_id: str) -> tuple[str, ModelScore] | None:
    lowered = model_id.lower()
    if not lowered.startswith("gemini-"):
        return None
    match = GOOGLE_RE.match(lowered)
    if match is None:
        return None
    tier = match.group("tier")
    major = int(match.group("major"))
    minor = int(match.group("minor") or "0")
    if major != GOOGLE_ALLOWED_MAJOR or tier not in GOOGLE_ALLOWED_TIERS:
        return None
    suffix = match.group("suffix")
    stable_rank = 1 if suffix is None else 0
    return tier, (major, minor, stable_rank, _suffix_stamp_rank(suffix))


def select_sota_model_ids(provider: str, model_ids: set[str]) -> list[tuple[str, str]]:
    """Select latest per family/tier to avoid exposing superseded models."""
    if provider == "openai":
        selected = _pick_latest_by_tier(model_ids, _parse_openai)
    elif provider == "anthropic":
        selected = _pick_latest_by_tier(model_ids, _parse_anthropic)
    elif provider == "google":
        selected = _pick_latest_by_tier(model_ids, _parse_google)
    else:
        selected = []

    if selected:
        return sorted(selected, key=lambda item: (item[0], item[1]))

    # Known providers use strict parsing/policy filters; unmatched models are excluded.
    if provider in {"openai", "anthropic", "google"}:
        return []

    # Unknown providers use permissive fallback.
    return [("default", model_id) for model_id in sorted(model_ids)[:3]]


def validate_model_id(model_id: str) -> None:
    """Validate a runtime model ID against project policy."""
    if ":" not in model_id:
        raise ValueError("model must use '<provider>:<model-id>' format")

    prefix, raw_model_id = model_id.split(":", maxsplit=1)
    if not raw_model_id.strip():
        raise ValueError("model id suffix must be non-empty")

    if prefix == "google-vertex":
        raise ValueError("google-vertex models are not allowed; use google-gla:*")

    if prefix not in KNOWN_PROVIDER_PREFIXES:
        raise ValueError(f"unsupported model provider '{prefix}'")

    provider = provider_from_model_id(model_id)
    if provider == "anthropic" and not select_sota_model_ids("anthropic", {raw_model_id}):
        raise ValueError("anthropic model must be version 4.5 or 4.6")

    if provider == "google" and not select_sota_model_ids("google", {raw_model_id}):
        raise ValueError("google model must be gemini-3* pro/flash with google-gla prefix")


# ---------------------------------------------------------------------------
# Local-only enforcement
# ---------------------------------------------------------------------------

_LOOPBACK_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}


class LocalOnlyViolationError(ValueError):
    """Raised when local-only mode would be violated by a model or endpoint."""


def has_cloud_suffix(model_id: str) -> bool:
    """Return True if an Ollama model reference routes through Ollama's cloud.

    Ollama's cloud/Turbo feature proxies cloud-resolved models through the
    local `ollama serve` process to ollama.com. The local wire endpoint stays
    at localhost, but the prompt still leaves the machine. The only reliable
    pre-request signal is the model tag: `:cloud` or a `-cloud`-suffixed tag
    (e.g. ``qwen3.5:cloud``, ``gpt-oss:120b-cloud``).

    Accepts references either bare (``qwen3.5:cloud``) or prefixed
    (``ollama:qwen3.5:cloud``).
    """
    if not model_id:
        return False
    # Strip an optional provider prefix: ollama:<repo>[:<tag>]
    reference = model_id.split(":", maxsplit=1)[1] if model_id.startswith("ollama:") else model_id
    # Split repo:tag — tag is the last :-separated segment.
    tag = (
        reference.rsplit(":", maxsplit=1)[1].lower()
        if ":" in reference
        else reference.lower()
    )
    return tag == "cloud" or tag.endswith("-cloud")


def _is_loopback_address(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback


def _resolve_host_addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise LocalOnlyViolationError(
            f"cannot resolve OLLAMA_BASE_URL host {host!r} under --local-only: {exc}"
        ) from exc
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            addresses.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    return addresses


def enforce_endpoint_locality(
    ollama_base_url: str | None,
    *,
    allow_hosts: Sequence[str] = (),
    context: str = "local-only",
) -> str:
    """Assert that ``OLLAMA_BASE_URL`` points at a loopback/allowlisted host.

    Returns the resolved host (for logging/manifest purposes).

    Raises :class:`LocalOnlyViolationError` if the URL is missing, has a non-HTTP
    scheme, is a hostname that resolves to any public address, or is a public
    IP literal.
    """
    if not ollama_base_url:
        raise LocalOnlyViolationError(
            f"[{context}] OLLAMA_BASE_URL is not set. "
            "Set OLLAMA_BASE_URL to a local Ollama endpoint "
            "(e.g. http://localhost:11434/v1) to use local-only mode."
        )

    parsed = urlparse(ollama_base_url)
    if parsed.scheme not in {"http", "https"}:
        raise LocalOnlyViolationError(
            f"[{context}] OLLAMA_BASE_URL must use http or https, got scheme "
            f"{parsed.scheme!r}"
        )
    host = parsed.hostname
    if not host:
        raise LocalOnlyViolationError(
            f"[{context}] OLLAMA_BASE_URL {ollama_base_url!r} has no host component"
        )

    host_lower = host.lower()
    allow_set = {h.strip().lower() for h in allow_hosts if h.strip()}

    # Loopback name?
    if host_lower in _LOOPBACK_HOSTNAMES:
        return host_lower

    # Explicit allowlist hit on the name as given.
    if host_lower in allow_set:
        return host_lower

    # IP literal?
    if _is_loopback_address(host):
        return host

    # Resolve hostname and require every address to be loopback (or the name
    # itself to be on the allowlist — already handled above).
    addresses = _resolve_host_addresses(host)
    if not addresses:
        raise LocalOnlyViolationError(
            f"[{context}] OLLAMA_BASE_URL host {host!r} did not resolve to any address"
        )
    non_loopback = [str(a) for a in addresses if not a.is_loopback]
    if non_loopback:
        raise LocalOnlyViolationError(
            f"[{context}] OLLAMA_BASE_URL host {host!r} resolves to non-local addresses "
            f"{non_loopback!r}; add it to IPL_LOCAL_ONLY_ALLOW_HOSTS if you trust this endpoint"
        )
    return host


def enforce_local_only(
    model_name: str,
    *,
    local_only_mode: bool,
    ollama_base_url: str | None = None,
    allow_hosts: Sequence[str] = (),
    context: str = "local-only",
) -> None:
    """Reject any extraction request that could leave the machine.

    No-op when ``local_only_mode`` is False. When True, raises
    :class:`LocalOnlyViolationError` if any of the following is true:

    1. The model's provider is not ``ollama``.
    2. The model reference carries an Ollama cloud suffix
       (``:cloud`` or ``-cloud`` tag suffix).
    3. ``ollama_base_url`` is unset, malformed, or resolves to a non-local
       host that isn't on ``allow_hosts``.

    Callers pass ``context`` (e.g. ``"API request"``, ``"batch CLI"``,
    ``"worker"``) so the error message names the enforcement path. Settings
    coupling is kept out on purpose so this can be reused anywhere.
    """
    if not local_only_mode:
        return

    provider = provider_from_model_id(model_name)
    if provider != "ollama":
        raise LocalOnlyViolationError(
            f"[{context}] model {model_name!r} is not an Ollama model "
            "(local-only mode requires an ollama:<model> reference)"
        )

    if has_cloud_suffix(model_name):
        raise LocalOnlyViolationError(
            f"[{context}] model {model_name!r} is an Ollama cloud-routed model "
            "(`:cloud` / `-cloud` suffix). Cloud-routed models proxy through "
            "ollama.com and are not permitted under local-only."
        )

    enforce_endpoint_locality(
        ollama_base_url,
        allow_hosts=allow_hosts,
        context=context,
    )
