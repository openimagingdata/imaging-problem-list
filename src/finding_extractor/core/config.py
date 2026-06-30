"""Centralized runtime configuration for finding_extractor."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from finding_extractor.llm.defaults import (
    MODEL_GOOGLE_GEMINI_3_1_FLASH_LITE_PREVIEW,
    MODEL_GOOGLE_GEMINI_3_FLASH_PREVIEW,
    MODEL_OPENAI_GPT_5_2,
    MODEL_OPENAI_GPT_5_4_MINI,
)
from finding_extractor.models import ReasoningLevel

DEFAULT_DB_PATH = Path(".finding_extractor.db")
DEFAULT_REDIS_URL = "redis://localhost:6379"
DEFAULT_MODEL = MODEL_GOOGLE_GEMINI_3_FLASH_PREVIEW
DEFAULT_FALLBACK_MODEL = MODEL_OPENAI_GPT_5_2
DEFAULT_CODING_MODEL = MODEL_OPENAI_GPT_5_2
DEFAULT_CODING_REASONING = "low"
DEFAULT_CODING_TERM_MODEL = MODEL_GOOGLE_GEMINI_3_FLASH_PREVIEW
DEFAULT_CODING_FALLBACK_MODEL = MODEL_GOOGLE_GEMINI_3_1_FLASH_LITE_PREVIEW
DEFAULT_CODING_MAX_CONCURRENCY = 8
DEFAULT_CODING_SEARCH_LIMIT = 6
DEFAULT_CODING_MAX_CANDIDATES = 12
DEFAULT_BATCH_RUN_DIR = Path(".batch_runs")
DEFAULT_BATCH_WORKERS = 4
DEFAULT_BATCH_TIMEOUT_SECONDS = 420
DEFAULT_BATCH_RETRIES = 1
DEFAULT_BATCH_STATUS_INTERVAL_SECONDS = 5.0
DEFAULT_BATCH_OUTPUT_SUFFIX = ".extracted.json"
DEFAULT_BATCH_RESUME = True
DEFAULT_EVAL_RUN_DIR = Path(".eval_runs")
DEFAULT_EVAL_WORKERS = 2
DEFAULT_EVAL_TIMEOUT_SECONDS = 120
DEFAULT_EVAL_RETRIES = 0
DEFAULT_EVAL_DATASET_DIR = Path("evals/datasets")
DEFAULT_CORS_ORIGINS = ["http://localhost:8000", "http://127.0.0.1:8000"]
DEFAULT_UPDATE_MODEL_LIST_INTERVAL_SECONDS = 48 * 60 * 60
DEFAULT_LOGFIRE_SERVICE_NAME = "finding-extractor"
DEFAULT_LOG_LEVEL = "WARNING"
DEFAULT_LOG_JSON = False
DEFAULT_ALLOW_UNKNOWN_MODEL_REASONING = False
DEFAULT_EXTRACTOR_MAX_SUBAGENT_CONCURRENCY = 5
DEFAULT_REVIEWER_ENABLED = True
DEFAULT_REVIEWER_REEXTRACT_ENABLED = True
DEFAULT_VLLM_GEMMA4_31B_BASE_URL: str | None = None
DEFAULT_VLLM_GPT_OSS_120B_BASE_URL: str | None = None
DEFAULT_CHUNKING_SEMANTIC_TRIGGER_SENTENCE_COUNT = 4
DEFAULT_CHUNKING_SEMANTIC_EMBEDDING_MODEL = "minishlab/potion-base-32M"
DEFAULT_CHUNKING_SEMANTIC_THRESHOLD = 0.8
DEFAULT_CHUNKING_SEMANTIC_CHUNK_SIZE = 2048
DEFAULT_CHUNKING_SEMANTIC_SIMILARITY_WINDOW = 3
DEFAULT_CHUNKING_SEMANTIC_SKIP_WINDOW = 0
DEFAULT_CHUNKING_IMPRESSION_LIST_CHUNKING_ENABLED = True
DEFAULT_CHUNKING_IMPRESSION_LIST_MAX_ITEMS_PER_CHUNK = 3
DEFAULT_CHUNKING_IMPRESSION_LIST_MIN_ITEMS_PER_CHUNK = 2
CONFIG_TOML_PATH = "config.toml"
_TOML_SECRET_KEYS = {
    "openai_api_key",
    "anthropic_api_key",
    "google_api_key",
    "openrouter_api_key",
    "vllm_api_key",
    "logfire_token",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "VLLM_API_KEY",
    "LOGFIRE_TOKEN",
}
_TOML_SECRET_KEYS_NORMALIZED = {key.lower() for key in _TOML_SECRET_KEYS}


class IPLTomlSettingsSource(TomlConfigSettingsSource):
    """TOML source for non-secret app configuration."""

    @staticmethod
    def _find_forbidden_keys(
        data: dict[str, object],
        *,
        path: tuple[str, ...] = (),
    ) -> list[str]:
        matches: list[str] = []
        for key, value in data.items():
            key_str = str(key)
            next_path = (*path, key_str)
            if key_str.lower() in _TOML_SECRET_KEYS_NORMALIZED:
                matches.append(".".join(next_path))
            if isinstance(value, dict):
                # ty can't narrow the generic dict type after isinstance; cast for the recursive call
                nested: dict[str, object] = value  # type: ignore[assignment]
                matches.extend(IPLTomlSettingsSource._find_forbidden_keys(nested, path=next_path))
        return matches

    def __call__(self) -> dict[str, object]:
        raw_data = super().__call__()
        forbidden = self._find_forbidden_keys(raw_data)
        if forbidden:
            formatted = ", ".join(sorted(forbidden))
            msg = (
                f"`{CONFIG_TOML_PATH}` is for non-secrets only; move these to environment variables: "
                f"{formatted}"
            )
            raise ValueError(msg)

        section_data: dict[str, object] = {}
        if isinstance(raw_data.get("ipl"), dict):
            section_data = dict(raw_data["ipl"])

        merged_data = {k: v for k, v in raw_data.items() if k != "ipl"}
        merged_data.update(section_data)
        return merged_data


class ExtractorSettings(BaseSettings):
    """Environment-first app settings with optional non-secret TOML overrides."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        toml_file=CONFIG_TOML_PATH,
        populate_by_name=True,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        toml_settings = IPLTomlSettingsSource(settings_cls, toml_file=CONFIG_TOML_PATH)
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            toml_settings,
            file_secret_settings,
        )

    db_path: Path = Field(
        default=DEFAULT_DB_PATH,
        validation_alias=AliasChoices(
            "IPL_DB_PATH",
        ),
    )
    redis_url: str = Field(
        default=DEFAULT_REDIS_URL,
        validation_alias=AliasChoices(
            "IPL_REDIS_URL",
        ),
    )
    redis_result_ttl: int = Field(
        default=3600,
        validation_alias=AliasChoices(
            "IPL_REDIS_RESULT_TTL",
        ),
    )
    default_model: str = Field(
        default=DEFAULT_MODEL,
        validation_alias=AliasChoices(
            "IPL_MODEL",
        ),
    )
    fallback_model: str | None = Field(
        default=DEFAULT_FALLBACK_MODEL,
        validation_alias=AliasChoices(
            "IPL_FALLBACK_MODEL",
        ),
    )
    coding_model: str = Field(
        default=DEFAULT_CODING_MODEL,
        validation_alias=AliasChoices(
            "IPL_CODING_MODEL",
        ),
    )
    coding_reasoning: ReasoningLevel | None = Field(
        default=DEFAULT_CODING_REASONING,
        validation_alias=AliasChoices(
            "IPL_CODING_REASONING",
        ),
    )
    coding_term_model: str | None = Field(
        default=DEFAULT_CODING_TERM_MODEL,
        validation_alias=AliasChoices(
            "IPL_CODING_TERM_MODEL",
        ),
    )
    coding_fallback_model: str | None = Field(
        default=DEFAULT_CODING_FALLBACK_MODEL,
        validation_alias=AliasChoices(
            "IPL_CODING_FALLBACK_MODEL",
        ),
    )
    coding_max_concurrency: int = Field(
        default=DEFAULT_CODING_MAX_CONCURRENCY,
        ge=1,
        le=32,
        validation_alias=AliasChoices(
            "IPL_CODING_MAX_CONCURRENCY",
        ),
    )
    coding_search_limit: int = Field(
        default=DEFAULT_CODING_SEARCH_LIMIT,
        ge=1,
        le=32,
        validation_alias=AliasChoices(
            "IPL_CODING_SEARCH_LIMIT",
        ),
    )
    coding_max_candidates: int = Field(
        default=DEFAULT_CODING_MAX_CANDIDATES,
        ge=1,
        le=64,
        validation_alias=AliasChoices(
            "IPL_CODING_MAX_CANDIDATES",
        ),
    )
    batch_run_dir: Path = Field(
        default=DEFAULT_BATCH_RUN_DIR,
        validation_alias=AliasChoices(
            "IPL_BATCH_RUN_DIR",
        ),
    )
    batch_workers: int = Field(
        default=DEFAULT_BATCH_WORKERS,
        ge=1,
        le=64,
        validation_alias=AliasChoices(
            "IPL_BATCH_WORKERS",
        ),
    )
    batch_timeout_seconds: int = Field(
        default=DEFAULT_BATCH_TIMEOUT_SECONDS,
        ge=10,
        validation_alias=AliasChoices(
            "IPL_BATCH_TIMEOUT_SECONDS",
        ),
    )
    batch_retries: int = Field(
        default=DEFAULT_BATCH_RETRIES,
        ge=0,
        le=10,
        validation_alias=AliasChoices(
            "IPL_BATCH_RETRIES",
        ),
    )
    batch_status_interval_seconds: float = Field(
        default=DEFAULT_BATCH_STATUS_INTERVAL_SECONDS,
        gt=0,
        validation_alias=AliasChoices(
            "IPL_BATCH_STATUS_INTERVAL_SECONDS",
        ),
    )
    batch_output_suffix: str = Field(
        default=DEFAULT_BATCH_OUTPUT_SUFFIX,
        validation_alias=AliasChoices(
            "IPL_BATCH_OUTPUT_SUFFIX",
        ),
    )
    batch_resume: bool = Field(
        default=DEFAULT_BATCH_RESUME,
        validation_alias=AliasChoices(
            "IPL_BATCH_RESUME",
        ),
    )
    eval_run_dir: Path = Field(
        default=DEFAULT_EVAL_RUN_DIR,
        validation_alias=AliasChoices(
            "IPL_EVAL_RUN_DIR",
        ),
    )
    eval_workers: int = Field(
        default=DEFAULT_EVAL_WORKERS,
        ge=1,
        le=16,
        validation_alias=AliasChoices(
            "IPL_EVAL_WORKERS",
        ),
    )
    eval_timeout_seconds: int = Field(
        default=DEFAULT_EVAL_TIMEOUT_SECONDS,
        ge=10,
        validation_alias=AliasChoices(
            "IPL_EVAL_TIMEOUT_SECONDS",
        ),
    )
    eval_retries: int = Field(
        default=DEFAULT_EVAL_RETRIES,
        ge=0,
        le=5,
        validation_alias=AliasChoices(
            "IPL_EVAL_RETRIES",
        ),
    )
    eval_dataset_dir: Path = Field(
        default=DEFAULT_EVAL_DATASET_DIR,
        validation_alias=AliasChoices(
            "IPL_EVAL_DATASET_DIR",
        ),
    )
    default_reasoning: ReasoningLevel | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "IPL_REASONING",
        ),
    )
    allow_unknown_model_reasoning: bool = Field(
        default=DEFAULT_ALLOW_UNKNOWN_MODEL_REASONING,
        validation_alias=AliasChoices(
            "IPL_ALLOW_UNKNOWN_MODEL_REASONING",
        ),
    )
    default_preset: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "IPL_PRESET",
        ),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY"),
    )
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY"),
    )
    google_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_API_KEY"),
    )
    openrouter_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENROUTER_API_KEY"),
    )
    update_model_list_interval_seconds: int = Field(
        default=DEFAULT_UPDATE_MODEL_LIST_INTERVAL_SECONDS,
        ge=60,
        validation_alias=AliasChoices(
            "IPL_MODEL_LIST_UPDATE_INTERVAL",
        ),
    )
    log_level: str = Field(
        default=DEFAULT_LOG_LEVEL,
        validation_alias=AliasChoices(
            "IPL_LOG_LEVEL",
        ),
    )
    log_json: bool = Field(
        default=DEFAULT_LOG_JSON,
        validation_alias=AliasChoices(
            "IPL_LOG_JSON",
        ),
    )
    logfire_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "IPL_LOGFIRE_ENABLED",
        ),
    )
    logfire_send: bool | str = Field(
        default="auto",
        validation_alias=AliasChoices(
            "IPL_LOGFIRE_SEND",
        ),
    )
    logfire_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "LOGFIRE_TOKEN",
        ),
    )
    logfire_service_name: str = Field(
        default=DEFAULT_LOGFIRE_SERVICE_NAME,
        validation_alias=AliasChoices(
            "IPL_LOGFIRE_SERVICE",
        ),
    )
    logfire_environment: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "IPL_LOGFIRE_ENV",
        ),
    )
    logfire_capture_headers: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "IPL_LOGFIRE_HEADERS",
        ),
    )
    logfire_system_metrics: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "IPL_LOGFIRE_METRICS",
        ),
    )
    logfire_instrument_provider_sdks: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "IPL_LOGFIRE_SDKS",
        ),
    )
    reviewer_enabled: bool = Field(
        default=DEFAULT_REVIEWER_ENABLED,
        validation_alias=AliasChoices(
            "IPL_REVIEWER_ENABLED",
        ),
    )
    reviewer_model: str | None = Field(
        default=MODEL_OPENAI_GPT_5_4_MINI,
        validation_alias=AliasChoices(
            "IPL_REVIEWER_MODEL",
        ),
    )
    reviewer_reasoning: ReasoningLevel | None = Field(
        default="low",
        validation_alias=AliasChoices(
            "IPL_REVIEWER_REASONING",
        ),
    )
    reviewer_reextract_enabled: bool = Field(
        default=DEFAULT_REVIEWER_REEXTRACT_ENABLED,
        validation_alias=AliasChoices(
            "IPL_REVIEWER_REEXTRACT_ENABLED",
        ),
    )
    subagent_timeout_seconds: float | None = Field(
        default=20.0,
        ge=1.0,
        le=300.0,
        validation_alias=AliasChoices(
            "IPL_SUBAGENT_TIMEOUT_SECONDS",
        ),
    )
    extractor_max_subagent_concurrency: int = Field(
        default=DEFAULT_EXTRACTOR_MAX_SUBAGENT_CONCURRENCY,
        ge=1,
        le=16,
        validation_alias=AliasChoices(
            "IPL_EXTRACTOR_MAX_SUBAGENT_CONCURRENCY",
        ),
    )
    chunking_semantic_trigger_sentence_count: int = Field(
        default=DEFAULT_CHUNKING_SEMANTIC_TRIGGER_SENTENCE_COUNT,
        ge=1,
        le=32,
        validation_alias=AliasChoices(
            "IPL_CHUNKING_SEMANTIC_TRIGGER_SENTENCE_COUNT",
        ),
    )
    chunking_semantic_embedding_model: str = Field(
        default=DEFAULT_CHUNKING_SEMANTIC_EMBEDDING_MODEL,
        validation_alias=AliasChoices(
            "IPL_CHUNKING_SEMANTIC_EMBEDDING_MODEL",
        ),
    )
    chunking_semantic_threshold: float = Field(
        default=DEFAULT_CHUNKING_SEMANTIC_THRESHOLD,
        gt=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "IPL_CHUNKING_SEMANTIC_THRESHOLD",
        ),
    )
    chunking_semantic_chunk_size: int = Field(
        default=DEFAULT_CHUNKING_SEMANTIC_CHUNK_SIZE,
        ge=64,
        le=16384,
        validation_alias=AliasChoices(
            "IPL_CHUNKING_SEMANTIC_CHUNK_SIZE",
        ),
    )
    chunking_semantic_similarity_window: int = Field(
        default=DEFAULT_CHUNKING_SEMANTIC_SIMILARITY_WINDOW,
        ge=1,
        le=16,
        validation_alias=AliasChoices(
            "IPL_CHUNKING_SEMANTIC_SIMILARITY_WINDOW",
        ),
    )
    chunking_semantic_skip_window: int = Field(
        default=DEFAULT_CHUNKING_SEMANTIC_SKIP_WINDOW,
        ge=0,
        le=8,
        validation_alias=AliasChoices(
            "IPL_CHUNKING_SEMANTIC_SKIP_WINDOW",
        ),
    )
    chunking_impression_list_chunking_enabled: bool = Field(
        default=DEFAULT_CHUNKING_IMPRESSION_LIST_CHUNKING_ENABLED,
        validation_alias=AliasChoices(
            "IPL_CHUNKING_IMPRESSION_LIST_CHUNKING_ENABLED",
        ),
    )
    chunking_impression_list_max_items_per_chunk: int = Field(
        default=DEFAULT_CHUNKING_IMPRESSION_LIST_MAX_ITEMS_PER_CHUNK,
        ge=1,
        le=8,
        validation_alias=AliasChoices(
            "IPL_CHUNKING_IMPRESSION_LIST_MAX_ITEMS_PER_CHUNK",
        ),
    )
    chunking_impression_list_min_items_per_chunk: int = Field(
        default=DEFAULT_CHUNKING_IMPRESSION_LIST_MIN_ITEMS_PER_CHUNK,
        ge=1,
        le=8,
        validation_alias=AliasChoices(
            "IPL_CHUNKING_IMPRESSION_LIST_MIN_ITEMS_PER_CHUNK",
        ),
    )
    local_only_mode: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "IPL_LOCAL_ONLY",
        ),
    )
    ollama_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OLLAMA_BASE_URL",
        ),
    )
    vllm_gemma4_31b_base_url: str | None = Field(
        default=DEFAULT_VLLM_GEMMA4_31B_BASE_URL,
        validation_alias=AliasChoices(
            "VLLM_GEMMA4_31B_BASE_URL",
        ),
    )
    vllm_gpt_oss_120b_base_url: str | None = Field(
        default=DEFAULT_VLLM_GPT_OSS_120B_BASE_URL,
        validation_alias=AliasChoices(
            "VLLM_GPT_OSS_120B_BASE_URL",
        ),
    )
    vllm_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VLLM_API_KEY",
        ),
    )
    vllm_local_only_allow_hosts: str = Field(
        default="",
        validation_alias=AliasChoices(
            "IPL_VLLM_LOCAL_ONLY_ALLOW_HOSTS",
            "VLLM_LOCAL_ONLY_ALLOW_HOSTS",
        ),
    )

    @property
    def vllm_local_only_allowed_hosts(self) -> frozenset[str]:
        """Return normalized vLLM hosts approved for local-only mode."""
        return frozenset(
            host.strip().lower()
            for host in self.vllm_local_only_allow_hosts.split(",")
            if host.strip()
        )

    def vllm_base_url_for_model_optional(self, model_id: str) -> str | None:
        """Return the configured vLLM base URL, or None when it is unset."""
        from finding_extractor.llm.policy import canonical_vllm_model_id

        canonical = canonical_vllm_model_id(model_id)
        if canonical == "google/gemma-4-31B-it":
            return self.vllm_gemma4_31b_base_url
        if canonical == "openai/gpt-oss-120b":
            return self.vllm_gpt_oss_120b_base_url
        raise ValueError(f"unsupported vLLM model {model_id!r}")

    def vllm_base_url_for_model(self, model_id: str) -> str:
        """Return the OpenAI-compatible API base URL for a supported vLLM model."""
        url = self.vllm_base_url_for_model_optional(model_id)
        if url is None:
            from finding_extractor.llm.policy import canonical_vllm_model_id

            canonical = canonical_vllm_model_id(model_id)
            if canonical == "google/gemma-4-31B-it":
                raise ValueError("VLLM_GEMMA4_31B_BASE_URL is required for this model")
            if canonical == "openai/gpt-oss-120b":
                raise ValueError("VLLM_GPT_OSS_120B_BASE_URL is required for this model")
        assert url is not None
        return url

    @model_validator(mode="before")
    @classmethod
    def _apply_local_only_defaults(cls, data: Any) -> Any:
        """Inject local-friendly defaults when ``local_only_mode`` is active.

        Runs before field validation so these values behave like real defaults
        (honoring explicit user overrides from env/TOML/CLI). Three fields
        bite users who forget them under local-only; handle them here instead
        of making every user memorize the incantation:

        - ``allow_unknown_model_reasoning`` → True (custom Modelfiles aren't in
          the catalog; the default False rejects them)
        - ``subagent_timeout_seconds`` → 300.0 (local models routinely need
          30-90s per chunk; default 20 times out mid-chunk)
        - ``batch_workers`` → 1 (Ollama serializes internally; concurrent
          report-level workers degrade quality and speed)
        - ``extractor_max_subagent_concurrency`` → 2 (Ollama 0.23.1 MLX
          threading fixes make c=2 safe for per-report chunk concurrency;
          c=1 is too conservative, c=4 starts breaking on 2026-05-14 sweep)

        An explicit env var / TOML / CLI value wins over the default because
        ``"<field>" in data`` is checked — pydantic-settings has already
        merged all sources into ``data`` by the time this runs.
        """
        if not isinstance(data, dict):
            return data
        local_only = data.get("local_only_mode") or data.get("IPL_LOCAL_ONLY")
        if not local_only:
            return data
        # Map each field to (value, env-alias). A field counts as "set" if
        # either its Python name or its env alias appears in the input dict.
        for field_name, env_alias, value in (
            ("allow_unknown_model_reasoning", "IPL_ALLOW_UNKNOWN_MODEL_REASONING", True),
            ("subagent_timeout_seconds", "IPL_SUBAGENT_TIMEOUT_SECONDS", 300.0),
            ("batch_workers", "IPL_BATCH_WORKERS", 1),
            ("extractor_max_subagent_concurrency", "IPL_EXTRACTOR_MAX_SUBAGENT_CONCURRENCY", 2),
        ):
            if field_name not in data and env_alias not in data:
                data[field_name] = value
        return data

    @model_validator(mode="after")
    def _enforce_local_only(self) -> ExtractorSettings:
        """When local_only_mode is True, validate all egress points are locked down.

        Rejects cloud ``default_model`` or a non-local ``OLLAMA_BASE_URL`` at
        load time so API, worker, and batch paths never silently reach cloud
        inference. The shared :func:`enforce_local_only` helper centralizes
        the actual checks.
        """
        if not self.local_only_mode:
            return self

        from finding_extractor.llm.policy import (
            enforce_local_only,
            provider_from_model_id,
        )

        # 1. Neutralize implicit model fields that would send data to cloud
        #    providers. Coding models are skipped — coding is blocked entirely
        #    in local-only mode by coding/runtime.py and the CLI.
        allowed_providers = {"ollama", "vllm"}
        if (
            self.fallback_model is not None
            and provider_from_model_id(self.fallback_model) not in allowed_providers
        ):
            self.fallback_model = None
        if (
            self.reviewer_model is not None
            and provider_from_model_id(self.reviewer_model) not in allowed_providers
        ):
            self.reviewer_enabled = False
            self.reviewer_model = None

        # 2. Validate every inference-capable model + endpoint in one call per
        #    model. The helper runs the provider, cloud-suffix / approved-model,
        #    and endpoint-locality gates in that order.
        def _enforce_model(model_name: str, *, context: str) -> None:
            enforce_local_only(
                model_name,
                local_only_mode=True,
                ollama_base_url=self.ollama_base_url,
                vllm_base_url=self.vllm_base_url_for_model_optional(model_name)
                if provider_from_model_id(model_name) == "vllm"
                else None,
                vllm_allowed_hosts=self.vllm_local_only_allowed_hosts,
                context=context,
            )

        _enforce_model(self.default_model, context="settings default_model")
        if self.fallback_model is not None:
            _enforce_model(self.fallback_model, context="settings fallback_model")
        if self.reviewer_enabled and self.reviewer_model is not None:
            _enforce_model(self.reviewer_model, context="settings reviewer_model")

        # 3. Force-disable Logfire.
        self.logfire_enabled = False
        self.logfire_token = None

        return self

    @field_validator("logfire_send")
    @classmethod
    def _validate_logfire_send(cls, value: bool | str) -> bool | str:
        if isinstance(value, bool):
            return value
        lowered = value.strip().lower()
        if lowered in {"auto", "true", "false"}:
            return lowered
        msg = "logfire send mode must be one of: 'auto', 'true', 'false', or a bool"
        raise ValueError(msg)

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized == "WARN":
            return "WARNING"
        if normalized in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}:
            return normalized
        msg = (
            "log level must be one of: CRITICAL, ERROR, WARNING, INFO, DEBUG, NOTSET "
            "(or WARN alias)"
        )
        raise ValueError(msg)

    @field_validator("vllm_gemma4_31b_base_url", "vllm_gpt_oss_120b_base_url")
    @classmethod
    def _normalize_vllm_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("vLLM base URL must not be empty")
        suffix = "/chat/completions"
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
        if not normalized.endswith("/v1"):
            raise ValueError("vLLM base URL must point at the OpenAI-compatible /v1 API root")
        return normalized

    @property
    def cors_origins(self) -> list[str]:
        """Return fixed default CORS origins for the API."""
        return DEFAULT_CORS_ORIGINS.copy()

    @field_validator("default_model")
    @classmethod
    def _validate_default_model(cls, value: str) -> str:
        from finding_extractor.llm.policy import validate_model_id

        validate_model_id(value)
        return value

    @field_validator("fallback_model")
    @classmethod
    def _validate_fallback_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from finding_extractor.llm.policy import validate_model_id

        validate_model_id(value)
        return value

    @field_validator("coding_model")
    @classmethod
    def _validate_coding_model(cls, value: str) -> str:
        from finding_extractor.llm.policy import validate_model_id

        validate_model_id(value)
        return value

    @field_validator("coding_term_model")
    @classmethod
    def _validate_coding_term_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from finding_extractor.llm.policy import validate_model_id

        validate_model_id(value)
        return value

    @field_validator("coding_fallback_model")
    @classmethod
    def _validate_coding_fallback_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from finding_extractor.llm.policy import validate_model_id

        validate_model_id(value)
        return value

    @field_validator("reviewer_model")
    @classmethod
    def _validate_reviewer_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from finding_extractor.llm.policy import validate_model_id

        validate_model_id(value)
        return value

    @field_validator("chunking_semantic_embedding_model")
    @classmethod
    def _validate_chunking_embedding_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("chunking_semantic_embedding_model must not be empty")
        return normalized

    @field_validator("chunking_impression_list_min_items_per_chunk")
    @classmethod
    def _validate_list_chunk_min_items(cls, value: int, info: ValidationInfo) -> int:
        max_items = info.data.get("chunking_impression_list_max_items_per_chunk")
        if max_items is not None and value > max_items:
            raise ValueError(
                "chunking_impression_list_min_items_per_chunk must be less than or equal to chunking_impression_list_max_items_per_chunk"
            )
        return value

    @field_validator("default_preset")
    @classmethod
    def _validate_default_preset(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from finding_extractor.llm.model_settings import PRESET_NAMES

        lowered = value.strip().lower()
        if lowered not in PRESET_NAMES:
            allowed = ", ".join(PRESET_NAMES)
            raise ValueError(f"Invalid preset {value!r}; must be one of: {allowed}")
        return lowered

    @field_validator("batch_output_suffix")
    @classmethod
    def _validate_batch_output_suffix(cls, value: str) -> str:
        if not value.startswith("."):
            raise ValueError("batch_output_suffix must start with '.'")
        return value


_settings_override: ExtractorSettings | None = None


@lru_cache(maxsize=1)
def _load_settings() -> ExtractorSettings:
    return ExtractorSettings()


def get_settings() -> ExtractorSettings:
    """Return process-global settings instance."""
    if _settings_override is not None:
        return _settings_override
    return _load_settings()


def clear_settings_cache() -> None:
    """Clear cached settings and any override (primarily for tests)."""
    global _settings_override
    _settings_override = None
    _load_settings.cache_clear()


def override_settings(settings: ExtractorSettings) -> None:
    """Replace the settings singleton with a pre-built instance.

    Used by the CLI to inject settings with overrides (e.g. ``--local-only``)
    so that downstream code calling ``get_settings()`` picks up the validated copy.
    """
    global _settings_override
    _settings_override = settings
