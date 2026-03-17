"""Canonical model IDs and curated common model list."""

from dataclasses import dataclass

MODEL_GOOGLE_GEMINI_3_FLASH_PREVIEW = "google-gla:gemini-3-flash-preview"
MODEL_GOOGLE_GEMINI_3_1_FLASH_LITE_PREVIEW = "google-gla:gemini-3.1-flash-lite-preview"
MODEL_GOOGLE_GEMINI_3_1_PRO_PREVIEW = "google-gla:gemini-3.1-pro-preview"
MODEL_OPENAI_GPT_5_2 = "openai:gpt-5.2"
MODEL_OPENAI_GPT_5_4_MINI = "openai-responses:gpt-5.4-mini"
MODEL_ANTHROPIC_CLAUDE_OPUS_4_6 = "anthropic:claude-opus-4-6"
MODEL_OLLAMA_QWEN3_30B_INSTRUCT = "ollama:qwen3:30b-instruct"
MODEL_OLLAMA_QWEN3_30B_THINKING = "ollama:qwen3:30b-thinking"
MODEL_OLLAMA_GPT_OSS_120B = "ollama:gpt-oss:120b"


@dataclass(frozen=True, slots=True)
class CommonModel:
    """One curated model choice for extraction/validation workflows."""

    model: str
    recommended_reasoning: str
    role: str


COMMON_MODELS: tuple[CommonModel, ...] = (
    CommonModel(
        model=MODEL_GOOGLE_GEMINI_3_FLASH_PREVIEW,
        recommended_reasoning="low",
        role="default extraction baseline",
    ),
    CommonModel(
        model=MODEL_OPENAI_GPT_5_2,
        recommended_reasoning="low",
        role="fallback baseline",
    ),
    CommonModel(
        model=MODEL_ANTHROPIC_CLAUDE_OPUS_4_6,
        recommended_reasoning="low",
        role="quality validator/extraction option",
    ),
    CommonModel(
        model=MODEL_GOOGLE_GEMINI_3_1_PRO_PREVIEW,
        recommended_reasoning="low",
        role="Google quality option",
    ),
    CommonModel(
        model=MODEL_GOOGLE_GEMINI_3_1_FLASH_LITE_PREVIEW,
        recommended_reasoning="low",
        role="Google fast low-cost option",
    ),
    CommonModel(
        model=MODEL_OLLAMA_QWEN3_30B_INSTRUCT,
        recommended_reasoning="none",
        role="local baseline",
    ),
    CommonModel(
        model=MODEL_OLLAMA_QWEN3_30B_THINKING,
        recommended_reasoning="low",
        role="local thinking-capable option",
    ),
    CommonModel(
        model=MODEL_OLLAMA_GPT_OSS_120B,
        recommended_reasoning="medium",
        role="local heavy reasoning option",
    ),
)
