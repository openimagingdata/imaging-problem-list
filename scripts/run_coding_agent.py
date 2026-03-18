#!/usr/bin/env python3
"""Run the production coding pipeline against a test extraction JSON file.

Usage:
    uv run --env-file .env python scripts/run_coding_agent.py scripts/test_data/extracted.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from finding_extractor.coding.runtime import run_coding
from finding_extractor.core.observability import configure_logfire
from finding_extractor.models import ExtractedReportFindings


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run production coding pipeline")
    parser.add_argument("input", type=Path, help="Input extraction JSON file")
    parser.add_argument("--model", default=None)
    parser.add_argument("--reasoning", default=None)
    args = parser.parse_args()

    configure_logfire(runtime="cli")

    data = json.loads(args.input.read_text())
    extraction = ExtractedReportFindings.model_validate(data)

    async def _progress(message: str) -> None:
        print(f"  {message}")

    result = await run_coding(
        extraction,
        model=args.model,
        reasoning=args.reasoning,
        progress_callback=_progress,
    )

    print(f"\nModel: {result.model_name} (reasoning: {result.reasoning_effort})")
    print(f"Duration: {result.duration_ms}ms")
    print(f"Coded: {result.coded_finding_count}, Unresolved: {result.unresolved_finding_count}")

    # Write JSON output
    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"{args.input.stem}_agent_coded.json"
    output_data = result.extraction.model_dump(mode="json")
    output_path.write_text(json.dumps(output_data, indent=2))
    print(f"Output: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
