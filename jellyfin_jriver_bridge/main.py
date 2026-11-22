"""
Jellyfin Cast → JRiver Media Center Bridge — application entry point.

Usage::

    python -m jellyfin_jriver_bridge            # uses config.yaml in cwd
    python -m jellyfin_jriver_bridge -c my.yaml  # explicit config
    python -m jellyfin_jriver_bridge -v          # debug logging
    python run.py                                # convenience wrapper
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

import yaml

from .service import BridgeService

logger = logging.getLogger("jellyfin-jriver-bridge")


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

def _load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _resolve_config_path(cli_path: str) -> str:
    """Try the CLI value first, then look next to this file, then give up."""
    if os.path.isfile(cli_path):
        return cli_path

    # Fallback: project root (one level above the package directory)
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(pkg_dir)
    candidate = os.path.join(project_root, os.path.basename(cli_path))
    if os.path.isfile(candidate):
        return candidate

    return cli_path  # will fail later with a clear message


# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

async def main() -> None:  # noqa: C901
    parser = argparse.ArgumentParser(
        description="Jellyfin Cast → JRiver Media Center Bridge"
    )
    parser.add_argument(
        "-c", "--config", default="config.yaml", help="Path to YAML config"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable DEBUG logging"
    )
    args = parser.parse_args()

    # ── config ────────────────────────────────────────────────────────
    config_path = _resolve_config_path(args.config)
    if not os.path.isfile(config_path):
        print(f"ERROR: config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    cfg = _load_config(config_path)
    log_level = "DEBUG" if args.verbose else cfg.get("log_level", "INFO")
    _setup_logging(log_level)
    logger.info("Config loaded from %s", config_path)

    # ── Resolve config directory ──────────────────────────────────────
    config_dir = os.path.dirname(os.path.abspath(config_path))

    jcfg = cfg.get("jriver", {})
    ccfg = cfg.get("cast", {})
    jellyfin_cfg = cfg.get("jellyfin", {})
    device_name = ccfg.get("device_name", "JRiver Media Center")
    cast_port = int(ccfg.get("port", 8009))

    bridge_service = BridgeService(cfg, config_dir)

    logger.info("╔══════════════════════════════════════════════════╗")
    logger.info("║   Jellyfin → JRiver Bridge  READY               ║")
    logger.info("╠══════════════════════════════════════════════════╣")
    logger.info("║  Device : %-38s ║", device_name)
    logger.info("║  Cast   : port %-33d ║", cast_port)
    logger.info("║  MCWS   : %-38s ║", f"http://{jcfg.get('host', 'localhost')}:{jcfg.get('port', 52199)}/MCWS/v1")
    if jellyfin_cfg and jellyfin_cfg.get("url"):
        logger.info("║  Jellyfin: %-37s ║", jellyfin_cfg["url"])
    logger.info("╚══════════════════════════════════════════════════╝")

    try:
        await bridge_service.start()
        # Keep running until cancelled
        while bridge_service.is_running:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        logger.info("Shutting down …")
        await bridge_service.stop()
        logger.info("Bye!")
