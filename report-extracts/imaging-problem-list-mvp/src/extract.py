import json, os, sys
from pathlib import Path
from typing import Iterable
from dotenv import load_dotenv
from tqdm import tqdm

from pydantic_ai import Agent
from src.schemas import ExtractionResult
from src.prompt import SYSTEM_INSTRUCTIONS

def load_jsonl(path: Path):
    with path.open() as f:
        for line in f:
            if line.strip():
                yield json.loads(line)

def main():
    load_dotenv()
    model_id = os.getenv("MODEL_ID", "openai:gpt-4o")
    agent = Agent(model_id, output_type=ExtractionResult, instructions=SYSTEM_INSTRUCTIONS)
    in_path = Path("data/sample_reports.jsonl")
    out_path = Path("data/predictions.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w") as out_f:
        for row in tqdm(load_jsonl(in_path), desc="Extracting"):
            rpt_id = row.get["report_id"]
            text = row["text"]
            result = agent.run_sync(
                f"REPORT_ID={rpt_id}\nREPORT_TEXT:\n{text}\n\nReturn structured output."
            )
            pred = result.output  # typed & validated (ExtractionResult)
            pred.report_id = rpt_id  # ensure match
            out_f.write(pred.model_dump_json() + "\n")

    print(f"Wrote predictions to {out_path.resolve()}")

if __name__ == "__main__":
    sys.exit(main())
