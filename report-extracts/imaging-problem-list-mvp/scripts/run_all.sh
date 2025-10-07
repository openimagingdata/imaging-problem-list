#!/usr/bin/env bash
set -euo pipefail
python -m src.extract
python -m src.evaluate
