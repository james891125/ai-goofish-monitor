"""Shopee-only test bootstrap; no legacy platform services are imported."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
