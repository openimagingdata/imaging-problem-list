# Imaging Problem List — LLM Extraction MVP

Runs a type-safe PydanticAI agent on a few sample reports to extract findings into a strict schema, then scores against labels (precision/recall/F1).

## Quickstart (local)

1. Create and activate a virtual env:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
   *(optional)* If you prefer `uv`, you can use it instead.

2. Install deps:
   ```bash
   pip install -r requirements.txt
   ```
   > Alternative from docs: `pip install "pydantic-ai-slim[openai]"`

3. Configure your key:
   ```bash
   cp .env.example .env
   # edit .env and add OPENAI_API_KEY
   ```

4. Run extraction + evaluation:
   ```bash
   bash scripts/run_all.sh
   ```

Outputs:
- `data/predictions.jsonl` — model outputs validated against `src/schemas.py`
- Console table with overall and per-finding metrics

## Notes
- Uses `Agent(..., output_type=ExtractionResult, instructions=...)` so the model **must** return your schema.
- Change model by editing `MODEL_ID` in `.env` (e.g., `openai:gpt-4o`).
- Extend `data/` with more reports/labels for a stronger demo.
