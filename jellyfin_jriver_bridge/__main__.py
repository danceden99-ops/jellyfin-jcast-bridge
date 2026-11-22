"""Allow running the package directly: python -m jellyfin_jriver_bridge"""
import asyncio
from .main import main

if __name__ == "__main__":
    asyncio.run(main())
