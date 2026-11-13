"""Paths owned by this checkout; no companion or Earth2Road installation required."""
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    PROJECT = Path(sys.executable).resolve().parent
else:
    PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / 'out'
