#!/usr/bin/env python3
"""Run the mih package bundled in the Model Iteration Harness plugin."""

from pathlib import Path
import sys


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

from mih.cli import main


if __name__ == "__main__":
    main()
