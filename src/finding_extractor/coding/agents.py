"""Factory helpers for coding pipeline agents."""

from __future__ import annotations

from pydantic_ai import Agent

from finding_extractor.coding.prompt import (
    FINDING_CODE_SELECTOR_SYSTEM,
    FINDING_TERM_SYSTEM,
    LOCATION_CODE_SELECTOR_SYSTEM,
    LOCATION_TERM_SYSTEM,
)
from finding_extractor.coding.types import (
    FindingCodeSelection,
    FindingTermsBatchOutput,
    LocationCodeSelection,
    LocationTermsBatchOutput,
)
from finding_extractor.llm.resilience import AgentModelRuntime, build_resilient_model


def build_coding_model_runtime(
    *,
    model_name: str,
    reasoning: str | None,
    fallback_model_name: str | None,
    max_concurrency: int,
) -> AgentModelRuntime:
    """Resolve the shared model stack used by all coding agents in a run."""

    return build_resilient_model(
        model_name,
        reasoning=reasoning,
        fallback_model_name=fallback_model_name,
        provider_request_max_concurrency=max_concurrency,
    )


def create_finding_term_agent(runtime: AgentModelRuntime) -> Agent[None, FindingTermsBatchOutput]:
    return Agent(
        runtime.model,
        system_prompt=FINDING_TERM_SYSTEM,
        output_type=FindingTermsBatchOutput,
        model_settings=runtime.model_settings,
        output_retries=2,
        name="finding_term_generator",
    )


def create_location_term_agent(runtime: AgentModelRuntime) -> Agent[None, LocationTermsBatchOutput]:
    return Agent(
        runtime.model,
        system_prompt=LOCATION_TERM_SYSTEM,
        output_type=LocationTermsBatchOutput,
        model_settings=runtime.model_settings,
        output_retries=2,
        name="location_term_generator",
    )


def create_finding_selector_agent(runtime: AgentModelRuntime) -> Agent[None, FindingCodeSelection]:
    return Agent(
        runtime.model,
        system_prompt=FINDING_CODE_SELECTOR_SYSTEM,
        output_type=FindingCodeSelection,
        model_settings=runtime.model_settings,
        output_retries=2,
        name="finding_code_selector",
    )


def create_location_selector_agent(runtime: AgentModelRuntime) -> Agent[None, LocationCodeSelection]:
    return Agent(
        runtime.model,
        system_prompt=LOCATION_CODE_SELECTOR_SYSTEM,
        output_type=LocationCodeSelection,
        model_settings=runtime.model_settings,
        output_retries=2,
        name="location_code_selector",
    )
