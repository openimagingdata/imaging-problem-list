"""Tests for centralized settings resolution."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from finding_extractor.core.config import (
    DEFAULT_BATCH_OUTPUT_SUFFIX,
    DEFAULT_BATCH_RESUME,
    DEFAULT_BATCH_RETRIES,
    DEFAULT_BATCH_RUN_DIR,
    DEFAULT_BATCH_STATUS_INTERVAL_SECONDS,
    DEFAULT_BATCH_TIMEOUT_SECONDS,
    DEFAULT_BATCH_WORKERS,
    DEFAULT_CHUNKING_IMPRESSION_LIST_CHUNKING_ENABLED,
    DEFAULT_CHUNKING_IMPRESSION_LIST_MAX_ITEMS_PER_CHUNK,
    DEFAULT_CHUNKING_IMPRESSION_LIST_MIN_ITEMS_PER_CHUNK,
    DEFAULT_CHUNKING_SEMANTIC_CHUNK_SIZE,
    DEFAULT_CHUNKING_SEMANTIC_EMBEDDING_MODEL,
    DEFAULT_CHUNKING_SEMANTIC_SIMILARITY_WINDOW,
    DEFAULT_CHUNKING_SEMANTIC_SKIP_WINDOW,
    DEFAULT_CHUNKING_SEMANTIC_THRESHOLD,
    DEFAULT_CHUNKING_SEMANTIC_TRIGGER_SENTENCE_COUNT,
    DEFAULT_CODING_FALLBACK_MODEL,
    DEFAULT_CODING_MAX_CANDIDATES,
    DEFAULT_CODING_MAX_CONCURRENCY,
    DEFAULT_CODING_MODEL,
    DEFAULT_CODING_REASONING,
    DEFAULT_CODING_SEARCH_LIMIT,
    DEFAULT_CORS_ORIGINS,
    DEFAULT_DB_PATH,
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_LOG_JSON,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MODEL,
    DEFAULT_REDIS_URL,
    DEFAULT_UPDATE_MODEL_LIST_INTERVAL_SECONDS,
    DEFAULT_VLLM_GEMMA4_31B_BASE_URL,
    DEFAULT_VLLM_GPT_OSS_120B_BASE_URL,
    clear_settings_cache,
    get_settings,
)


def test_settings_defaults_without_env(tmp_path, monkeypatch):
    """Defaults should match current runtime behavior."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("IPL_DB_PATH", raising=False)
    monkeypatch.delenv("IPL_REDIS_URL", raising=False)
    monkeypatch.delenv("IPL_MODEL", raising=False)
    monkeypatch.delenv("IPL_REASONING", raising=False)

    settings = get_settings()

    assert settings.db_path == DEFAULT_DB_PATH
    assert settings.redis_url == DEFAULT_REDIS_URL
    assert settings.default_model == DEFAULT_MODEL
    assert settings.fallback_model == DEFAULT_FALLBACK_MODEL
    assert settings.default_reasoning is None
    assert settings.coding_model == DEFAULT_CODING_MODEL
    assert settings.coding_reasoning == DEFAULT_CODING_REASONING
    assert settings.coding_fallback_model == DEFAULT_CODING_FALLBACK_MODEL
    assert settings.coding_max_concurrency == DEFAULT_CODING_MAX_CONCURRENCY
    assert settings.coding_search_limit == DEFAULT_CODING_SEARCH_LIMIT
    assert settings.coding_max_candidates == DEFAULT_CODING_MAX_CANDIDATES
    assert settings.allow_unknown_model_reasoning is False
    assert settings.batch_run_dir == DEFAULT_BATCH_RUN_DIR
    assert settings.batch_workers == DEFAULT_BATCH_WORKERS
    assert settings.batch_timeout_seconds == DEFAULT_BATCH_TIMEOUT_SECONDS
    assert settings.batch_retries == DEFAULT_BATCH_RETRIES
    assert settings.batch_status_interval_seconds == DEFAULT_BATCH_STATUS_INTERVAL_SECONDS
    assert settings.batch_output_suffix == DEFAULT_BATCH_OUTPUT_SUFFIX
    assert settings.batch_resume is DEFAULT_BATCH_RESUME
    assert settings.openai_api_key is None
    assert settings.anthropic_api_key is None
    assert settings.google_api_key is None
    assert settings.vllm_api_key is None
    assert settings.vllm_gemma4_31b_base_url == DEFAULT_VLLM_GEMMA4_31B_BASE_URL
    assert settings.vllm_gpt_oss_120b_base_url == DEFAULT_VLLM_GPT_OSS_120B_BASE_URL
    assert settings.vllm_local_only_allowed_hosts == frozenset()
    assert settings.update_model_list_interval_seconds == DEFAULT_UPDATE_MODEL_LIST_INTERVAL_SECONDS
    assert settings.cors_origins == DEFAULT_CORS_ORIGINS
    assert settings.log_level == DEFAULT_LOG_LEVEL
    assert settings.log_json is DEFAULT_LOG_JSON
    assert settings.logfire_enabled is False
    assert settings.logfire_send == "auto"
    assert settings.reviewer_model == "openai-responses:gpt-5.4-mini"
    assert settings.reviewer_reasoning == "low"
    assert settings.reviewer_reextract_enabled is True
    assert (
        settings.chunking_semantic_trigger_sentence_count
        == DEFAULT_CHUNKING_SEMANTIC_TRIGGER_SENTENCE_COUNT
    )
    assert settings.chunking_semantic_embedding_model == DEFAULT_CHUNKING_SEMANTIC_EMBEDDING_MODEL
    assert settings.chunking_semantic_threshold == DEFAULT_CHUNKING_SEMANTIC_THRESHOLD
    assert settings.chunking_semantic_chunk_size == DEFAULT_CHUNKING_SEMANTIC_CHUNK_SIZE
    assert (
        settings.chunking_semantic_similarity_window == DEFAULT_CHUNKING_SEMANTIC_SIMILARITY_WINDOW
    )
    assert settings.chunking_semantic_skip_window == DEFAULT_CHUNKING_SEMANTIC_SKIP_WINDOW
    assert (
        settings.chunking_impression_list_chunking_enabled
        is DEFAULT_CHUNKING_IMPRESSION_LIST_CHUNKING_ENABLED
    )
    assert (
        settings.chunking_impression_list_max_items_per_chunk
        == DEFAULT_CHUNKING_IMPRESSION_LIST_MAX_ITEMS_PER_CHUNK
    )
    assert (
        settings.chunking_impression_list_min_items_per_chunk
        == DEFAULT_CHUNKING_IMPRESSION_LIST_MIN_ITEMS_PER_CHUNK
    )


def test_settings_support_ipl_env_names(tmp_path, monkeypatch):
    """`IPL_*` environment names configure runtime settings."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_DB_PATH", "/tmp/ipl.db")
    monkeypatch.setenv("IPL_REDIS_URL", "redis://localhost:6380")
    monkeypatch.setenv("IPL_MODEL", "ollama:llama3")
    monkeypatch.setenv("IPL_FALLBACK_MODEL", "ollama:llama3.3")
    monkeypatch.setenv("IPL_REASONING", "low")
    monkeypatch.setenv("IPL_CODING_MODEL", "openai:gpt-5-mini")
    monkeypatch.setenv("IPL_CODING_REASONING", "minimal")
    monkeypatch.setenv("IPL_CODING_FALLBACK_MODEL", "google-gla:gemini-3.1-flash-lite-preview")
    monkeypatch.setenv("IPL_CODING_MAX_CONCURRENCY", "7")
    monkeypatch.setenv("IPL_CODING_SEARCH_LIMIT", "9")
    monkeypatch.setenv("IPL_CODING_MAX_CANDIDATES", "15")
    monkeypatch.setenv("IPL_ALLOW_UNKNOWN_MODEL_REASONING", "true")
    monkeypatch.setenv("IPL_BATCH_RUN_DIR", "/tmp/batch-runs")
    monkeypatch.setenv("IPL_BATCH_WORKERS", "8")
    monkeypatch.setenv("IPL_BATCH_TIMEOUT_SECONDS", "777")
    monkeypatch.setenv("IPL_BATCH_RETRIES", "3")
    monkeypatch.setenv("IPL_BATCH_STATUS_INTERVAL_SECONDS", "2.5")
    monkeypatch.setenv("IPL_BATCH_OUTPUT_SUFFIX", ".candidate.json")
    monkeypatch.setenv("IPL_BATCH_RESUME", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-test")
    monkeypatch.setenv("VLLM_API_KEY", "vllm-test")
    monkeypatch.setenv("VLLM_GEMMA4_31B_BASE_URL", "https://example.org/gemma/v1/chat/completions")
    monkeypatch.setenv("VLLM_GPT_OSS_120B_BASE_URL", "https://example.org/gpt-oss/v1")
    monkeypatch.setenv("IPL_VLLM_LOCAL_ONLY_ALLOW_HOSTS", "example.org, vllm.internal")
    monkeypatch.setenv("IPL_MODEL_LIST_UPDATE_INTERVAL", "86400")
    monkeypatch.setenv("IPL_LOG_LEVEL", "debug")
    monkeypatch.setenv("IPL_LOG_JSON", "true")
    monkeypatch.setenv("IPL_REVIEWER_MODEL", "openai:gpt-5-mini")
    monkeypatch.setenv("IPL_REVIEWER_REASONING", "low")
    monkeypatch.setenv("IPL_REVIEWER_REEXTRACT_ENABLED", "false")
    monkeypatch.setenv("IPL_CHUNKING_SEMANTIC_TRIGGER_SENTENCE_COUNT", "5")
    monkeypatch.setenv("IPL_CHUNKING_SEMANTIC_EMBEDDING_MODEL", "minishlab/potion-base-32M")
    monkeypatch.setenv("IPL_CHUNKING_SEMANTIC_THRESHOLD", "0.72")
    monkeypatch.setenv("IPL_CHUNKING_SEMANTIC_CHUNK_SIZE", "1536")
    monkeypatch.setenv("IPL_CHUNKING_SEMANTIC_SIMILARITY_WINDOW", "4")
    monkeypatch.setenv("IPL_CHUNKING_SEMANTIC_SKIP_WINDOW", "1")
    monkeypatch.setenv("IPL_CHUNKING_IMPRESSION_LIST_CHUNKING_ENABLED", "false")
    monkeypatch.setenv("IPL_CHUNKING_IMPRESSION_LIST_MAX_ITEMS_PER_CHUNK", "4")
    monkeypatch.setenv("IPL_CHUNKING_IMPRESSION_LIST_MIN_ITEMS_PER_CHUNK", "2")

    settings = get_settings()

    assert settings.db_path == Path("/tmp/ipl.db")
    assert settings.redis_url == "redis://localhost:6380"
    assert settings.default_model == "ollama:llama3"
    assert settings.fallback_model == "ollama:llama3.3"
    assert settings.default_reasoning == "low"
    assert settings.coding_model == "openai:gpt-5-mini"
    assert settings.coding_reasoning == "minimal"
    assert settings.coding_fallback_model == "google-gla:gemini-3.1-flash-lite-preview"
    assert settings.coding_max_concurrency == 7
    assert settings.coding_search_limit == 9
    assert settings.coding_max_candidates == 15
    assert settings.allow_unknown_model_reasoning is True
    assert settings.batch_run_dir == Path("/tmp/batch-runs")
    assert settings.batch_workers == 8
    assert settings.batch_timeout_seconds == 777
    assert settings.batch_retries == 3
    assert settings.batch_status_interval_seconds == 2.5
    assert settings.batch_output_suffix == ".candidate.json"
    assert settings.batch_resume is False
    assert settings.openai_api_key == "openai-test"
    assert settings.anthropic_api_key == "anthropic-test"
    assert settings.google_api_key == "google-test"
    assert settings.vllm_api_key == "vllm-test"
    assert settings.vllm_gemma4_31b_base_url == "https://example.org/gemma/v1"
    assert settings.vllm_gpt_oss_120b_base_url == "https://example.org/gpt-oss/v1"
    assert settings.vllm_local_only_allowed_hosts == frozenset({"example.org", "vllm.internal"})
    assert settings.update_model_list_interval_seconds == 86400
    assert settings.cors_origins == DEFAULT_CORS_ORIGINS
    assert settings.log_level == "DEBUG"
    assert settings.log_json is True
    assert settings.reviewer_model == "openai:gpt-5-mini"
    assert settings.reviewer_reasoning == "low"
    assert settings.reviewer_reextract_enabled is False
    assert settings.chunking_semantic_trigger_sentence_count == 5
    assert settings.chunking_semantic_embedding_model == "minishlab/potion-base-32M"
    assert settings.chunking_semantic_threshold == pytest.approx(0.72)
    assert settings.chunking_semantic_chunk_size == 1536
    assert settings.chunking_semantic_similarity_window == 4
    assert settings.chunking_semantic_skip_window == 1
    assert settings.chunking_impression_list_chunking_enabled is False
    assert settings.chunking_impression_list_max_items_per_chunk == 4
    assert settings.chunking_impression_list_min_items_per_chunk == 2


def test_settings_support_logfire_env_names(tmp_path, monkeypatch):
    """Logfire settings should be configurable from env vars."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_LOGFIRE_ENABLED", "true")
    monkeypatch.setenv("IPL_LOGFIRE_SEND", "false")
    monkeypatch.setenv("LOGFIRE_TOKEN", "test-token")
    monkeypatch.setenv("IPL_LOGFIRE_SERVICE", "custom-service")
    monkeypatch.setenv("IPL_LOGFIRE_ENV", "test")
    monkeypatch.setenv("IPL_LOGFIRE_HEADERS", "true")
    monkeypatch.setenv("IPL_LOGFIRE_METRICS", "true")
    monkeypatch.setenv("IPL_LOGFIRE_SDKS", "true")

    settings = get_settings()

    assert settings.logfire_enabled is True
    assert settings.logfire_send == "false"
    assert settings.logfire_token == "test-token"
    assert settings.logfire_service_name == "custom-service"
    assert settings.logfire_environment == "test"
    assert settings.logfire_capture_headers is True
    assert settings.logfire_system_metrics is True
    assert settings.logfire_instrument_provider_sdks is True


def test_settings_reject_invalid_logfire_send_value(tmp_path, monkeypatch):
    """Logfire send mode only accepts bool/auto/true/false."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_LOGFIRE_SEND", "maybe")

    with pytest.raises(ValidationError, match="logfire send mode must be one of"):
        get_settings()


def test_settings_reject_invalid_log_level(tmp_path, monkeypatch):
    """Log level should only accept known Python logging levels."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_LOG_LEVEL", "verbose")

    with pytest.raises(ValidationError, match="log level must be one of"):
        get_settings()


def test_settings_reject_disallowed_default_model_prefix(tmp_path, monkeypatch):
    """`google-vertex:*` defaults are rejected in env settings."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_MODEL", "google-vertex:gemini-3-pro")

    with pytest.raises(ValidationError, match="google-vertex models are not allowed"):
        get_settings()


def test_settings_reject_disallowed_fallback_model_prefix(tmp_path, monkeypatch):
    """`google-vertex:*` fallback models are rejected in env settings."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_FALLBACK_MODEL", "google-vertex:gemini-3-pro")

    with pytest.raises(ValidationError, match="google-vertex models are not allowed"):
        get_settings()


def test_settings_reject_disallowed_coding_model_prefix(tmp_path, monkeypatch):
    """`google-vertex:*` coding defaults are rejected in env settings."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_CODING_MODEL", "google-vertex:gemini-3-pro")

    with pytest.raises(ValidationError, match="google-vertex models are not allowed"):
        get_settings()


def test_settings_reject_disallowed_coding_fallback_model_prefix(tmp_path, monkeypatch):
    """`google-vertex:*` coding fallback models are rejected in env settings."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_CODING_FALLBACK_MODEL", "google-vertex:gemini-3-pro")

    with pytest.raises(ValidationError, match="google-vertex models are not allowed"):
        get_settings()


def test_settings_reject_empty_chunking_embedding_model(tmp_path, monkeypatch):
    """Chunking embedding model cannot be empty."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_CHUNKING_SEMANTIC_EMBEDDING_MODEL", "   ")

    with pytest.raises(
        ValidationError, match="chunking_semantic_embedding_model must not be empty"
    ):
        get_settings()


def test_settings_reject_invalid_chunking_semantic_threshold(tmp_path, monkeypatch):
    """Chunking semantic threshold must be in (0, 1]."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_CHUNKING_SEMANTIC_THRESHOLD", "2")

    with pytest.raises(ValidationError, match="less than or equal to 1"):
        get_settings()


def test_settings_reject_invalid_chunking_sentence_trigger(tmp_path, monkeypatch):
    """Chunking sentence trigger must be >= 1."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_CHUNKING_SEMANTIC_TRIGGER_SENTENCE_COUNT", "0")

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        get_settings()


def test_settings_reject_invalid_impression_list_min_max(tmp_path, monkeypatch):
    """Impression list min-items must not exceed max-items."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_CHUNKING_IMPRESSION_LIST_MIN_ITEMS_PER_CHUNK", "5")
    monkeypatch.setenv("IPL_CHUNKING_IMPRESSION_LIST_MAX_ITEMS_PER_CHUNK", "3")

    with pytest.raises(
        ValidationError,
        match="chunking_impression_list_min_items_per_chunk must be less than or equal to",
    ):
        get_settings()


def test_settings_load_non_secret_values_from_config_toml(tmp_path, monkeypatch):
    """Optional config.toml should load non-secret app settings."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        """
[ipl]
db_path = "/tmp/from-toml.db"
redis_url = "redis://localhost:6390"
default_model = "ollama:llama3.3"
fallback_model = "ollama:llama3"
default_reasoning = "none"
batch_run_dir = ".runs"
batch_workers = 6
batch_timeout_seconds = 555
batch_retries = 2
batch_status_interval_seconds = 1.25
batch_output_suffix = ".gold-candidate.json"
batch_resume = true
update_model_list_interval_seconds = 600
logfire_enabled = true
logfire_send = "auto"
log_level = "warning"
log_json = true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    settings = get_settings()

    assert settings.db_path == Path("/tmp/from-toml.db")
    assert settings.redis_url == "redis://localhost:6390"
    assert settings.default_model == "ollama:llama3.3"
    assert settings.fallback_model == "ollama:llama3"
    assert settings.default_reasoning == "none"
    assert settings.batch_run_dir == Path(".runs")
    assert settings.batch_workers == 6
    assert settings.batch_timeout_seconds == 555
    assert settings.batch_retries == 2
    assert settings.batch_status_interval_seconds == 1.25
    assert settings.batch_output_suffix == ".gold-candidate.json"
    assert settings.batch_resume is True
    assert settings.update_model_list_interval_seconds == 600
    assert settings.cors_origins == DEFAULT_CORS_ORIGINS
    assert settings.log_level == "WARNING"
    assert settings.log_json is True
    assert settings.logfire_enabled is True
    assert settings.logfire_send == "auto"


def test_env_overrides_config_toml_values(tmp_path, monkeypatch):
    """Environment variables should take precedence over config.toml."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        """
[ipl]
default_model = "ollama:llama3.3"
default_reasoning = "none"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("IPL_MODEL", "openai:gpt-5-mini")
    monkeypatch.setenv("IPL_REASONING", "high")

    settings = get_settings()

    assert settings.default_model == "openai:gpt-5-mini"
    assert settings.default_reasoning == "high"


def test_settings_reject_invalid_default_reasoning(tmp_path, monkeypatch):
    """Invalid IPL_REASONING should be rejected at config load time."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_REASONING", "turbo")

    with pytest.raises(ValidationError, match="literal_error"):
        get_settings()


def test_settings_accept_valid_default_reasoning_values(tmp_path, monkeypatch):
    """All valid reasoning levels should be accepted."""
    monkeypatch.chdir(tmp_path)
    for level in ("none", "minimal", "low", "medium", "high"):
        monkeypatch.setenv("IPL_REASONING", level)
        settings = get_settings()
        assert settings.default_reasoning == level
        clear_settings_cache()


def test_settings_default_preset_is_none_when_unset(tmp_path, monkeypatch):
    """default_preset should be None when IPL_PRESET is not set."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("IPL_PRESET", raising=False)

    settings = get_settings()
    assert settings.default_preset is None


def test_settings_accept_valid_preset(tmp_path, monkeypatch):
    """Valid IPL_PRESET values should be accepted."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_PRESET", "fast")

    settings = get_settings()
    assert settings.default_preset == "fast"


def test_settings_accept_preset_case_insensitive(tmp_path, monkeypatch):
    """IPL_PRESET should be case-insensitive."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_PRESET", "BALANCED")

    settings = get_settings()
    assert settings.default_preset == "balanced"


def test_settings_reject_invalid_preset(tmp_path, monkeypatch):
    """Invalid IPL_PRESET should be rejected at config load time."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IPL_PRESET", "turbo")

    with pytest.raises(ValidationError, match="Invalid preset"):
        get_settings()


def test_settings_reject_secrets_in_config_toml(tmp_path, monkeypatch):
    """config.toml rejects secret keys to keep credentials env-only."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        """
[ipl]
openai_api_key = "should-not-be-here"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non-secrets only"):
        get_settings()


def test_settings_reject_secrets_in_nested_config_toml_section(tmp_path, monkeypatch):
    """config.toml rejects secret keys even when nested in other sections."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        """
[secrets]
OPENAI_API_KEY = "should-not-be-here"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non-secrets only"):
        get_settings()
