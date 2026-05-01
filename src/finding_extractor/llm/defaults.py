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
MODEL_OLLAMA_QWEN35_35B_A3B = "ollama:qwen3.5:35b-a3b"
MODEL_OLLAMA_QWEN35_27B = "ollama:qwen3.5:27b"
MODEL_OLLAMA_QWEN35_9B = "ollama:qwen3.5:9b"
MODEL_OLLAMA_QWEN36_35B_A3B_Q8 = "ollama:qwen3.6:35b-a3b-q8_0"
MODEL_OLLAMA_QWEN36_35B_A3B_MLX_BF16 = "ollama:qwen3.6:35b-a3b-mlx-bf16"
MODEL_OLLAMA_QWEN36_35B_A3B_BF16 = "ollama:qwen3.6:35b-a3b-bf16"
MODEL_OLLAMA_GEMMA4_26B_MXFP8 = "ollama:gemma4:26b-mxfp8"
MODEL_OLLAMA_MEDGEMMA_27B = "ollama:medgemma:27b"
MODEL_VLLM_GEMMA4_31B = "vllm:google/gemma-4-31B-it"
MODEL_VLLM_GPT_OSS_120B = "vllm:openai/gpt-oss-120b"


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
        model=MODEL_OLLAMA_QWEN36_35B_A3B_MLX_BF16,
        recommended_reasoning="none",
        role="local default extractor (Qwen3.6 MoE MLX-bf16, 70GB; 1.68x faster than Q8)",
    ),
    CommonModel(
        model=MODEL_OLLAMA_QWEN36_35B_A3B_BF16,
        recommended_reasoning="low",
        role="local default reviewer (Qwen3.6 MoE bf16 GGUF, 71GB; best TP/FP ratio)",
    ),
    CommonModel(
        model=MODEL_OLLAMA_QWEN36_35B_A3B_Q8,
        recommended_reasoning="none",
        role="local Q8 alternative (38GB; slower than MLX-bf16 on Apple Silicon)",
    ),
    CommonModel(
        model=MODEL_OLLAMA_GEMMA4_26B_MXFP8,
        recommended_reasoning="none",
        role="local quality (Gemma 4 MoE MXFP8, 26GB)",
    ),
    CommonModel(
        model=MODEL_OLLAMA_MEDGEMMA_27B,
        recommended_reasoning="none",
        role="local medical specialist (MedGemma 27B, 17GB)",
    ),
    CommonModel(
        model=MODEL_OLLAMA_QWEN35_9B,
        recommended_reasoning="none",
        role="local ultralight (6GB)",
    ),
    CommonModel(
        model=MODEL_OLLAMA_QWEN3_30B_INSTRUCT,
        recommended_reasoning="none",
        role="local Qwen3 baseline",
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
    CommonModel(
        model=MODEL_VLLM_GEMMA4_31B,
        recommended_reasoning="none",
        role="on-prem vLLM Gemma 4 31B extractor",
    ),
    CommonModel(
        model=MODEL_VLLM_GPT_OSS_120B,
        recommended_reasoning="medium",
        role="on-prem vLLM GPT OSS 120B heavy reasoning option",
    ),
)
