"""Deterministic section chunking for modular extraction throughput.

Policy:
1. Deterministic section split happens upstream in the orchestrator.
2. Only `findings` and `impression` should be chunked for extraction work.
3. Compute true sentence spans first (not sentence-chunk count).
4. If sentence count is below configured threshold (default: 4), do not chunk.
5. For `impression`: prefer deterministic list chunking when list structure exists.
6. Otherwise run semantic chunking (with sentence-group fallback on semantic failure).
7. Final semantic chunks are capped at max sentences per chunk (default: 3).

This module intentionally avoids LLM adjudication for chunk boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import chonkie_core
import structlog

from finding_extractor.extractor.impression_chunker import ImpressionListChunker
from finding_extractor.extractor.report_sections import section_header_aliases

logger = structlog.get_logger(__name__)
TARGET_SECTIONS = {"findings", "impression"}
DEFAULT_SENTENCE_DELIMITERS = [". ", "! ", "? "]
DEFAULT_INCLUDE_DELIM = "prev"
DEFAULT_MIN_CHARS_PER_SENTENCE = 12


@dataclass(frozen=True)
class ChunkingSettings:
    """Runtime configuration for sentence-first semantic chunking."""

    semantic_trigger_sentence_count: int = 4
    max_sentences_per_chunk: int = 3
    semantic_embedding_model: str = "minishlab/potion-base-32M"
    semantic_threshold: float = 0.8
    semantic_chunk_size: int = 2048
    semantic_similarity_window: int = 3
    semantic_skip_window: int = 0
    impression_list_chunking_enabled: bool = True
    impression_list_max_items_per_chunk: int = 3
    impression_list_min_items_per_chunk: int = 2


@dataclass(frozen=True)
class SectionChunk:
    """A chunk span extracted from one report section."""

    start_index: int
    end_index: int
    text: str


@dataclass(frozen=True)
class ChunkingDiagnostics:
    """Chunking diagnostics suitable for logging and telemetry."""

    strategy: str
    chunk_count: int
    sentence_count: int
    semantic_applied: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ChunkingResult:
    """Chunking output bundle for one section."""

    chunks: tuple[SectionChunk, ...]
    diagnostics: ChunkingDiagnostics


def _single_chunk(section_text: str) -> tuple[SectionChunk, ...]:
    if not section_text:
        return ()
    return (SectionChunk(start_index=0, end_index=len(section_text), text=section_text),)


def _strip_leading_section_heading(section_name: str, section_text: str) -> str:
    """Remove a leading section header label while preserving body content."""
    aliases = section_header_aliases(section_name)
    if not aliases or not section_text:
        return section_text

    lines = section_text.splitlines(keepends=True)
    first_non_empty_idx: int | None = None
    for idx, line in enumerate(lines):
        if line.strip():
            first_non_empty_idx = idx
            break
    if first_non_empty_idx is None:
        return section_text

    line = lines[first_non_empty_idx]
    line_ending = "\n" if line.endswith("\n") else ""
    content = line[:-1] if line_ending else line
    stripped_line = content.strip()

    for alias in sorted(aliases, key=len, reverse=True):
        alias_pat = re.escape(str(alias))
        inline_pat = re.compile(
            (
                r"^\s*(?:#{1,6}\s*)?"
                r"(?:\*\*)?\s*"
                + alias_pat
                + r"\s*(?:\*\*)?\s*[:\-]\s*(.*)$"
            ),
            re.IGNORECASE,
        )
        match = inline_pat.match(content)
        if match is None:
            continue

        remainder = match.group(1)
        remainder = re.sub(r"^\s*\*\*\s*", "", remainder)
        remainder = re.sub(r"\s*\*\*\s*$", "", remainder)
        if remainder.strip():
            lines[first_non_empty_idx] = remainder + line_ending
        else:
            lines[first_non_empty_idx] = ""

        candidate = "".join(lines).lstrip("\n")
        if candidate.strip():
            return candidate
        return section_text

    normalized = re.sub(r"[#*`]", "", stripped_line).strip().lower().strip(":- ")
    if normalized in aliases:
        lines[first_non_empty_idx] = ""
        candidate = "".join(lines).lstrip("\n")
        if candidate.strip():
            return candidate

    return section_text


def _normalize_chunks(chunks: list[SectionChunk], section_text: str) -> tuple[SectionChunk, ...]:
    """Validate monotonic, non-overlapping, near-full-coverage chunks."""
    if not chunks:
        return ()

    ordered = sorted(chunks, key=lambda chunk: chunk.start_index)
    cursor = 0
    normalized: list[SectionChunk] = []

    for chunk in ordered:
        if chunk.start_index < cursor:
            raise ValueError("chunk boundaries overlap")
        if chunk.end_index <= chunk.start_index:
            raise ValueError("chunk has non-positive span")
        if chunk.end_index > len(section_text):
            raise ValueError("chunk span exceeds section length")

        gap = section_text[cursor : chunk.start_index]
        if gap and gap.strip():
            raise ValueError("chunk boundaries leave non-whitespace gap")

        text = section_text[chunk.start_index : chunk.end_index]
        if not text:
            raise ValueError("chunk text is empty")

        normalized.append(
            SectionChunk(
                start_index=chunk.start_index,
                end_index=chunk.end_index,
                text=text,
            )
        )
        cursor = chunk.end_index

    trailing = section_text[cursor:]
    if trailing and trailing.strip():
        raise ValueError("chunk boundaries do not fully cover section text")

    return tuple(normalized)


def _coerce_raw_chunks(raw_chunks, section_text: str) -> tuple[SectionChunk, ...]:
    candidates: list[SectionChunk] = []
    section_len = len(section_text)
    for raw in raw_chunks:
        start = max(0, int(raw.start_index))
        end = min(section_len, int(raw.end_index))
        if start >= end:
            continue
        candidates.append(
            SectionChunk(
                start_index=start,
                end_index=end,
                text=section_text[start:end],
            )
        )
    if not candidates:
        return _single_chunk(section_text)
    return _normalize_chunks(candidates, section_text)


def _split_sentence_texts(section_text: str) -> list[str]:
    """Split text into sentence-like spans using Chonkie's core splitter."""
    text_bytes = section_text.encode("utf-8")
    patterns = [d.encode("utf-8") for d in DEFAULT_SENTENCE_DELIMITERS]
    offsets = chonkie_core.split_pattern_offsets(
        text_bytes,
        patterns=patterns,
        include_delim=DEFAULT_INCLUDE_DELIM,
        min_chars=DEFAULT_MIN_CHARS_PER_SENTENCE,
    )
    parts = [text_bytes[start:end].decode("utf-8") for start, end in offsets]
    return [part for part in parts if part]


def _sentence_spans(section_text: str) -> tuple[SectionChunk, ...]:
    """Return true sentence spans for count/control-flow and sentence grouping."""
    if not section_text.strip():
        return ()

    try:
        sentence_texts = _split_sentence_texts(section_text)
        if not sentence_texts:
            return _single_chunk(section_text)

        spans: list[SectionChunk] = []
        cursor = 0
        for sentence in sentence_texts:
            start = cursor
            end = cursor + len(sentence)
            spans.append(
                SectionChunk(
                    start_index=start,
                    end_index=end,
                    text=section_text[start:end],
                )
            )
            cursor = end
        return _normalize_chunks(spans, section_text)
    except Exception:
        logger.warning("sentence splitting failed; using passthrough chunk", exc_info=True)
        return _single_chunk(section_text)


def _semantic_candidates(section_text: str, settings: ChunkingSettings) -> tuple[SectionChunk, ...]:
    """Generate semantic chunks with Chonkie SemanticChunker."""
    import warnings

    from chonkie import SemanticChunker

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=".*unauthenticated requests.*HF Hub.*",
            module="huggingface_hub",
        )
        chunker = SemanticChunker(
            embedding_model=settings.semantic_embedding_model,
            threshold=settings.semantic_threshold,
            chunk_size=settings.semantic_chunk_size,
            similarity_window=settings.semantic_similarity_window,
            min_sentences_per_chunk=1,
            min_characters_per_sentence=24,
            delim=DEFAULT_SENTENCE_DELIMITERS,
            include_delim="prev",
            skip_window=settings.semantic_skip_window,
        )
    raw_chunks = chunker.chunk(section_text)
    if not raw_chunks:
        return _single_chunk(section_text)
    return _coerce_raw_chunks(raw_chunks, section_text)


def _group_sentence_spans(
    sentence_spans: tuple[SectionChunk, ...],
    section_text: str,
    *,
    max_sentences_per_chunk: int,
) -> tuple[SectionChunk, ...]:
    if not sentence_spans:
        return ()

    groups: list[list[SectionChunk]] = []
    i = 0
    total = len(sentence_spans)
    while i < total:
        remaining = total - i
        if remaining <= max_sentences_per_chunk:
            take = remaining
        else:
            take = max_sentences_per_chunk
            # Avoid a trailing single-sentence remainder when possible.
            if remaining - take == 1 and max_sentences_per_chunk > 2:
                take = max_sentences_per_chunk - 1
        groups.append(list(sentence_spans[i : i + take]))
        i += take

    chunks: list[SectionChunk] = []
    for group in groups:
        start = group[0].start_index
        end = group[-1].end_index
        chunks.append(
            SectionChunk(start_index=start, end_index=end, text=section_text[start:end])
        )
    return _normalize_chunks(chunks, section_text)


def _semantic_index_for_position(
    position: int,
    semantic_chunks: tuple[SectionChunk, ...],
    *,
    start_idx: int,
) -> int:
    idx = start_idx
    while idx + 1 < len(semantic_chunks) and position >= semantic_chunks[idx].end_index:
        idx += 1
    while idx > 0 and position < semantic_chunks[idx].start_index:
        idx -= 1
    return idx


def _group_sentences_by_semantics(
    sentence_spans: tuple[SectionChunk, ...],
    semantic_chunks: tuple[SectionChunk, ...],
    section_text: str,
    *,
    max_sentences_per_chunk: int,
) -> tuple[SectionChunk, ...]:
    if not sentence_spans:
        return ()
    if not semantic_chunks:
        return _group_sentence_spans(
            sentence_spans, section_text, max_sentences_per_chunk=max_sentences_per_chunk
        )

    semantic_ids: list[int] = []
    sem_idx = 0
    for sentence in sentence_spans:
        midpoint = (sentence.start_index + sentence.end_index) // 2
        sem_idx = _semantic_index_for_position(midpoint, semantic_chunks, start_idx=sem_idx)
        semantic_ids.append(sem_idx)

    groups: list[list[SectionChunk]] = []
    current: list[SectionChunk] = []
    current_semantic_id: int | None = None

    for sentence, semantic_id in zip(sentence_spans, semantic_ids, strict=True):
        if not current:
            current = [sentence]
            current_semantic_id = semantic_id
            continue
        if (
            semantic_id != current_semantic_id
            or len(current) >= max_sentences_per_chunk
        ):
            groups.append(current)
            current = [sentence]
            current_semantic_id = semantic_id
            continue
        current.append(sentence)
    if current:
        groups.append(current)

    chunks: list[SectionChunk] = []
    for group in groups:
        start = group[0].start_index
        end = group[-1].end_index
        chunks.append(
            SectionChunk(start_index=start, end_index=end, text=section_text[start:end])
        )
    return _normalize_chunks(chunks, section_text)


def _impression_list_chunks(
    section_text: str,
    settings: ChunkingSettings,
) -> tuple[SectionChunk, ...] | None:
    """Chunk impression list-items into grouped chunks when list formatting exists."""
    chunker = ImpressionListChunker(
        max_items_per_chunk=max(1, settings.impression_list_max_items_per_chunk),
        min_items_per_chunk=max(1, settings.impression_list_min_items_per_chunk),
    )
    raw_chunks = chunker.chunk(section_text)
    if len(raw_chunks) <= 1:
        return None
    return _coerce_raw_chunks(raw_chunks, section_text)


async def chunk_section_text(
    *,
    section_name: str,
    section_text: str,
    settings: ChunkingSettings,
) -> ChunkingResult:
    """Chunk a single section into extraction chunks using sentence-first policy."""
    section_text = _strip_leading_section_heading(section_name, section_text)
    sentence_spans = _sentence_spans(section_text)
    sentence_count = len(sentence_spans)

    if section_name not in TARGET_SECTIONS:
        chunks = _single_chunk(section_text)
        return ChunkingResult(
            chunks=chunks,
            diagnostics=ChunkingDiagnostics(
                strategy="non_target_section_passthrough",
                chunk_count=len(chunks),
                sentence_count=sentence_count,
                semantic_applied=False,
            ),
        )

    if sentence_count < settings.semantic_trigger_sentence_count:
        chunks = _single_chunk(section_text)
        return ChunkingResult(
            chunks=chunks,
            diagnostics=ChunkingDiagnostics(
                strategy="below_threshold_passthrough",
                chunk_count=len(chunks),
                sentence_count=sentence_count,
                semantic_applied=False,
            ),
        )

    sentence_grouped_chunks = _group_sentence_spans(
        sentence_spans,
        section_text,
        max_sentences_per_chunk=max(1, settings.max_sentences_per_chunk),
    )

    if section_name == "impression":
        if settings.impression_list_chunking_enabled:
            try:
                list_chunks = _impression_list_chunks(section_text, settings)
            except Exception:
                logger.warning("impression list chunking failed; continuing", exc_info=True)
                list_chunks = None
            if list_chunks is not None:
                return ChunkingResult(
                    chunks=list_chunks,
                    diagnostics=ChunkingDiagnostics(
                        strategy="impression_list_grouped",
                        chunk_count=len(list_chunks),
                        sentence_count=sentence_count,
                        semantic_applied=False,
                    ),
                )

        # Impression policy: if no list structure, always attempt semantic chunking.
        try:
            semantic_chunks = _semantic_candidates(section_text, settings)
        except Exception as exc:
            logger.warning(
                "impression semantic chunking failed; falling back to sentence chunks",
                exc_info=True,
            )
            return ChunkingResult(
                chunks=sentence_grouped_chunks,
                diagnostics=ChunkingDiagnostics(
                    strategy="impression_semantic_failed_sentence_fallback",
                    chunk_count=len(sentence_grouped_chunks),
                    sentence_count=sentence_count,
                    semantic_applied=False,
                    warnings=(f"semantic_error:{type(exc).__name__}",),
                ),
            )

        semantic_grouped_chunks = _group_sentences_by_semantics(
            sentence_spans,
            semantic_chunks,
            section_text,
            max_sentences_per_chunk=max(1, settings.max_sentences_per_chunk),
        )
        return ChunkingResult(
            chunks=semantic_grouped_chunks,
            diagnostics=ChunkingDiagnostics(
                strategy="impression_semantic_grouped",
                chunk_count=len(semantic_grouped_chunks),
                sentence_count=sentence_count,
                semantic_applied=True,
            ),
        )

    if sentence_count <= settings.semantic_trigger_sentence_count:
        return ChunkingResult(
            chunks=sentence_grouped_chunks,
            diagnostics=ChunkingDiagnostics(
                strategy="sentence_grouped",
                chunk_count=len(sentence_grouped_chunks),
                sentence_count=sentence_count,
                semantic_applied=False,
            ),
        )

    try:
        semantic_chunks = _semantic_candidates(section_text, settings)
    except Exception as exc:
        logger.warning(
            "semantic chunking failed; falling back to sentence chunks",
            exc_info=True,
        )
        return ChunkingResult(
            chunks=sentence_grouped_chunks,
            diagnostics=ChunkingDiagnostics(
                strategy="semantic_failed_sentence_fallback",
                chunk_count=len(sentence_grouped_chunks),
                sentence_count=sentence_count,
                semantic_applied=False,
                warnings=(f"semantic_error:{type(exc).__name__}",),
            ),
        )

    semantic_grouped_chunks = _group_sentences_by_semantics(
        sentence_spans,
        semantic_chunks,
        section_text,
        max_sentences_per_chunk=max(1, settings.max_sentences_per_chunk),
    )
    return ChunkingResult(
        chunks=semantic_grouped_chunks,
        diagnostics=ChunkingDiagnostics(
            strategy="semantic_grouped",
            chunk_count=len(semantic_grouped_chunks),
            sentence_count=sentence_count,
            semantic_applied=True,
        ),
    )
