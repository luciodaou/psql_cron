#!/usr/bin/env python3
"""
Root entry point for backwards compatibility.
Delegates to the modular psql_cron package.
"""
import sys
from pathlib import Path

# Ensure src/ directory is on sys.path for direct python execution
src_dir = Path(__file__).resolve().parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from psql_cron.main import main

if __name__ == "__main__":
    main()
