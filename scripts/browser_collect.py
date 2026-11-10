#!/usr/bin/env python3
"""Optional local CLI. Never starts the application, scheduler or AI services."""
from pathlib import Path
import sys

# Support `python scripts/browser_collect.py` from a downloaded Windows ZIP.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.experimental.browser_collector import run_cli

if __name__ == "__main__":
    raise SystemExit(run_cli())
