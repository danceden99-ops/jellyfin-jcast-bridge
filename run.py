#!/usr/bin/env python3
"""
Convenience launcher — run from the project root:

    python run.py
    python run.py -c my_config.yaml
    python run.py -v
"""
import asyncio
import os
import sys

# Ensure the package can be imported when running as a script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jellyfin_jriver_bridge.main import main  # noqa: E402

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
