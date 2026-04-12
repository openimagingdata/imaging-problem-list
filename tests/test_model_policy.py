"""Tests for runtime model-id validation policy and local-only mode."""

import ipaddress
from collections import namedtuple

import pytest

from finding_extractor.core.config import ExtractorSettings, clear_settings_cache
from finding_extractor.llm.model_settings import ollama_needs_native_output
from finding_extractor.llm.policy import (
    LocalOnlyViolationError,
    enforce_endpoint_locality,
    enforce_local_only,
    has_cloud_suffix,
    validate_model_id,
)


def test_validate_model_id_accepts_openai():
    validate_model_id("openai:gpt-5-mini")


def test_validate_model_id_accepts_ollama():
    validate_model_id("ollama:llama3.3")


def test_validate_model_id_accepts_anthropic_45():
    validate_model_id("anthropic:claude-sonnet-4-5")


def test_validate_model_id_accepts_gemini3_gla():
    validate_model_id("google-gla:gemini-3.1-pro-preview")


def test_validate_model_id_rejects_google_vertex():
    with pytest.raises(ValueError, match="google-vertex models are not allowed"):
        validate_model_id("google-vertex:gemini-3-pro")


def test_validate_model_id_rejects_old_anthropic():
    with pytest.raises(ValueError, match="anthropic model must be version 4.5 or 4.6"):
        validate_model_id("anthropic:claude-sonnet-4-0")


def test_validate_model_id_rejects_old_gemini():
    with pytest.raises(ValueError, match="google model must be gemini-3\\* pro/flash"):
        validate_model_id("google-gla:gemini-2.5-pro")


def test_validate_model_id_accepts_openrouter():
    validate_model_id("openrouter:anthropic/claude-sonnet-4-5")


def test_validate_model_id_accepts_openrouter_openai_model():
    validate_model_id("openrouter:openai/gpt-5")


def test_validate_model_id_rejects_bad_format():
    with pytest.raises(ValueError, match="model must use"):
        validate_model_id("gpt-5-mini")


# ---------------------------------------------------------------------------
# ollama_needs_native_output
# ---------------------------------------------------------------------------


class TestOllamaNeedsNativeOutput:
    """Detect which Ollama families need NativeOutput mode."""

    def test_non_ollama_models_never_need_native(self):
        assert ollama_needs_native_output("openai:gpt-5.2") is False
        assert ollama_needs_native_output("anthropic:claude-opus-4-6") is False
        assert ollama_needs_native_output("google-gla:gemini-3-flash-preview") is False

    def test_gpt_oss_uses_tools(self):
        assert ollama_needs_native_output("ollama:gpt-oss:120b") is False
        assert ollama_needs_native_output("ollama:gpt-oss:20b") is False

    def test_llama_uses_tools(self):
        assert ollama_needs_native_output("ollama:llama3.3:latest") is False
        assert ollama_needs_native_output("ollama:llama4:latest") is False

    def test_qwen_uses_tools(self):
        assert ollama_needs_native_output("ollama:qwen3:30b-instruct") is False
        assert ollama_needs_native_output("ollama:qwen3.5:27b") is False
        assert ollama_needs_native_output("ollama:qwen3.5:35b-a3b-mlx-bf16") is False

    def test_nemotron_uses_tools(self):
        assert ollama_needs_native_output("ollama:nemotron-3-super:120b") is False

    def test_nemotron_cascade_2_needs_native(self):
        assert ollama_needs_native_output("ollama:nemotron-cascade-2") is True

    def test_gemma4_needs_native(self):
        assert ollama_needs_native_output("ollama:gemma4:26b") is True
        assert ollama_needs_native_output("ollama:gemma4:31b") is True

    def test_gemma3_needs_native(self):
        assert ollama_needs_native_output("ollama:gemma3:27b") is True

    def test_deepseek_needs_native(self):
        assert ollama_needs_native_output("ollama:deepseek-r1:70b") is True
        assert ollama_needs_native_output("ollama:deepseek-r1:32b") is True

    def test_medgemma_needs_native(self):
        assert ollama_needs_native_output("ollama:MedAIBase/MedGemma1.0:27b") is True
        assert ollama_needs_native_output("ollama:alibayram/medgemma:27b") is True

    def test_custom_modelfile_names_need_native(self):
        assert ollama_needs_native_output("ollama:gemma4-radextract") is True

    def test_unknown_ollama_family_conservative_default(self):
        assert ollama_needs_native_output("ollama:some-unknown-model:7b") is True


# ---------------------------------------------------------------------------
# Local-only mode tests
# ---------------------------------------------------------------------------


class TestLocalOnlyMode:
    """Tests for the local_only_mode settings enforcement."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        clear_settings_cache()
        yield
        clear_settings_cache()

    def _make_settings(self, **overrides) -> ExtractorSettings:
        """Build settings with local-only defaults, applying overrides."""
        defaults = {
            "local_only_mode": True,
            "default_model": "ollama:qwen3.5:35b-a3b",
            "fallback_model": None,
            "reviewer_model": None,
            "coding_model": "ollama:qwen3.5:35b-a3b",
            "coding_term_model": None,
            "coding_fallback_model": None,
            "ollama_base_url": "http://localhost:11434/v1",
        }
        defaults.update(overrides)
        return ExtractorSettings(**defaults)

    def test_accepts_all_ollama_models(self):
        settings = self._make_settings()
        assert settings.local_only_mode is True

    def test_clears_cloud_fallback_model(self):
        settings = self._make_settings(fallback_model="openai:gpt-5.2")
        assert settings.fallback_model is None

    def test_keeps_ollama_fallback_model(self):
        settings = self._make_settings(fallback_model="ollama:qwen3.5:9b")
        assert settings.fallback_model == "ollama:qwen3.5:9b"

    def test_disables_cloud_reviewer(self):
        settings = self._make_settings(
            reviewer_enabled=True,
            reviewer_model="anthropic:claude-opus-4-6",
        )
        assert settings.reviewer_enabled is False
        assert settings.reviewer_model is None

    def test_keeps_ollama_reviewer(self):
        settings = self._make_settings(
            reviewer_enabled=True,
            reviewer_model="ollama:qwen3.5:27b",
        )
        assert settings.reviewer_enabled is True
        assert settings.reviewer_model == "ollama:qwen3.5:27b"

    def test_forces_logfire_disabled(self):
        settings = self._make_settings(logfire_enabled=True)
        assert settings.logfire_enabled is False

    def test_clears_logfire_token(self):
        settings = self._make_settings(logfire_token="pylf_v1_test_token")
        assert settings.logfire_token is None

    def test_does_not_enforce_when_disabled(self):
        """When local_only_mode is False, cloud models are allowed."""
        settings = ExtractorSettings(
            local_only_mode=False,
            default_model="openai:gpt-5.2",
        )
        assert settings.local_only_mode is False

    # --- Layer 1 hardening (new in this pass) ------------------------------

    def test_rejects_cloud_default_model(self):
        """IPL_LOCAL_ONLY=true + IPL_MODEL=openai:* must fail at settings load."""
        with pytest.raises(ValueError, match="not an Ollama model"):
            ExtractorSettings(
                local_only_mode=True,
                default_model="openai:gpt-5.2",
                ollama_base_url="http://localhost:11434/v1",
            )

    def test_rejects_missing_ollama_base_url(self):
        with pytest.raises(ValueError, match="OLLAMA_BASE_URL is not set"):
            ExtractorSettings(
                local_only_mode=True,
                default_model="ollama:qwen3.5:35b-a3b",
                ollama_base_url=None,
            )

    def test_rejects_cloud_suffix_default_model(self):
        with pytest.raises(ValueError, match="cloud-routed"):
            ExtractorSettings(
                local_only_mode=True,
                default_model="ollama:qwen3.5:cloud",
                ollama_base_url="http://localhost:11434/v1",
            )


# ---------------------------------------------------------------------------
# has_cloud_suffix
# ---------------------------------------------------------------------------


class TestHasCloudSuffix:
    @pytest.mark.parametrize(
        "model_id",
        [
            "ollama:qwen3.5:cloud",
            "ollama:glm-5:cloud",
            "ollama:kimi-k2.5:cloud",
            "ollama:gpt-oss:120b-cloud",
            "ollama:Qwen3.5:CLOUD",  # case-insensitive
            "ollama:qwen3.5:35B-CLOUD",
            "qwen3.5:cloud",  # bare reference
            "gpt-oss:120b-cloud",
        ],
    )
    def test_detects_cloud_suffix(self, model_id: str):
        assert has_cloud_suffix(model_id) is True

    @pytest.mark.parametrize(
        "model_id",
        [
            "ollama:qwen3.5:35b-a3b",
            "ollama:gpt-oss:120b",
            "ollama:gemma4-radextract",
            "ollama:llama3.3:latest",
            "ollama:cloudy:7b",  # "cloudy" != "cloud"
            "qwen3.5:35b-a3b",
            "",
        ],
    )
    def test_accepts_non_cloud(self, model_id: str):
        assert has_cloud_suffix(model_id) is False


# ---------------------------------------------------------------------------
# enforce_endpoint_locality
# ---------------------------------------------------------------------------


_AddrInfo = namedtuple("_AddrInfo", ["family", "type", "proto", "canonname", "sockaddr"])


def _fake_getaddrinfo_public(*_args, **_kwargs):
    return [_AddrInfo(2, 1, 6, "", ("93.184.216.34", 0))]


class TestEnforceEndpointLocality:
    def test_accepts_loopback_hostname(self):
        assert enforce_endpoint_locality("http://localhost:11434/v1") == "localhost"

    def test_accepts_ipv4_loopback(self):
        assert enforce_endpoint_locality("http://127.0.0.1:11434/v1") == "127.0.0.1"

    def test_accepts_ipv6_loopback(self):
        assert enforce_endpoint_locality("http://[::1]:11434/v1") == "::1"

    def test_rejects_missing_url(self):
        with pytest.raises(LocalOnlyViolationError, match="not set"):
            enforce_endpoint_locality(None)

    def test_rejects_non_http_scheme(self):
        with pytest.raises(LocalOnlyViolationError, match="http or https"):
            enforce_endpoint_locality("grpc://localhost:11434")

    def test_rejects_public_ip_literal(self, monkeypatch):
        monkeypatch.setattr("socket.getaddrinfo", _fake_getaddrinfo_public)
        with pytest.raises(LocalOnlyViolationError, match="non-local"):
            enforce_endpoint_locality("https://93.184.216.34/v1")

    def test_rejects_public_hostname(self, monkeypatch):
        monkeypatch.setattr("socket.getaddrinfo", _fake_getaddrinfo_public)
        with pytest.raises(LocalOnlyViolationError, match="non-local"):
            enforce_endpoint_locality("https://ollama.example.com/v1")

    def test_accepts_allowlisted_hostname(self, monkeypatch):
        # Allowlist hits BEFORE DNS, so the public resolution never runs.
        monkeypatch.setattr("socket.getaddrinfo", _fake_getaddrinfo_public)
        assert (
            enforce_endpoint_locality(
                "http://ollama.internal/v1",
                allow_hosts=["ollama.internal"],
            )
            == "ollama.internal"
        )

    def test_rejects_unresolvable_hostname(self, monkeypatch):
        def _raise(*_args, **_kwargs):
            import socket as _socket
            raise _socket.gaierror("name resolution failed")

        monkeypatch.setattr("socket.getaddrinfo", _raise)
        with pytest.raises(LocalOnlyViolationError, match="cannot resolve"):
            enforce_endpoint_locality("http://nope.invalid/v1")


# ---------------------------------------------------------------------------
# enforce_local_only (combined gates)
# ---------------------------------------------------------------------------


_LOCAL_URL = "http://localhost:11434/v1"


class TestEnforceLocalOnly:
    def test_noop_when_disabled(self):
        # Would fail every gate, but disabled → no-op.
        enforce_local_only(
            "openai:gpt-5.2",
            local_only_mode=False,
            ollama_base_url=None,
        )

    def test_rejects_cloud_provider(self):
        with pytest.raises(LocalOnlyViolationError, match="not an Ollama model"):
            enforce_local_only(
                "openai:gpt-5.2",
                local_only_mode=True,
                ollama_base_url=_LOCAL_URL,
            )

    @pytest.mark.parametrize(
        "cloud_model",
        [
            "ollama:qwen3.5:cloud",
            "ollama:gpt-oss:120b-cloud",
            "ollama:Qwen3.5:CLOUD",
        ],
    )
    def test_rejects_cloud_suffix(self, cloud_model: str):
        with pytest.raises(LocalOnlyViolationError, match="cloud-routed"):
            enforce_local_only(
                cloud_model,
                local_only_mode=True,
                ollama_base_url=_LOCAL_URL,
            )

    def test_rejects_public_endpoint(self, monkeypatch):
        monkeypatch.setattr("socket.getaddrinfo", _fake_getaddrinfo_public)
        with pytest.raises(LocalOnlyViolationError, match="non-local"):
            enforce_local_only(
                "ollama:qwen3.5:35b-a3b",
                local_only_mode=True,
                ollama_base_url="https://ollama.example.com/v1",
            )

    def test_accepts_local_ollama(self):
        # Should not raise.
        enforce_local_only(
            "ollama:qwen3.5:35b-a3b",
            local_only_mode=True,
            ollama_base_url=_LOCAL_URL,
        )

    def test_error_message_names_context(self):
        with pytest.raises(LocalOnlyViolationError, match=r"\[API request\]"):
            enforce_local_only(
                "openai:gpt-5.2",
                local_only_mode=True,
                ollama_base_url=_LOCAL_URL,
                context="API request",
            )

    def test_ip_address_is_not_special_cased(self):
        # A literal private IP outside loopback should still be rejected
        # unless on the allowlist.
        assert not ipaddress.ip_address("10.0.0.1").is_loopback
