"""
Bridge Service Manager.

Encapsulates the lifecycle of the bridge components (JRiver MCWS,
Jellyfin player, Eureka, Cast Discovery, and Cast Server) so it can
be cleanly started, stopped, restarted, and health-checked by either
the CLI runner or the Windows System Tray app.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable, Optional

from .bridge.controller import BridgeController
from .cast_outward.manager import OutwardCastManager
from .cast_receiver.discovery import CastDiscovery
from .cast_receiver.eureka import EurekaServer
from .cast_receiver.server import CastServer
from .cert_utils import generate_self_signed_cert
from .jellyfin.client import JellyfinRemotePlayer
from .jriver.mcws import MCWSClient

logger = logging.getLogger("jellyfin-jriver-bridge")


class BridgeService:
    """Manages the full lifecycle and health state of the bridge."""

    def __init__(self, config: dict, config_dir: str):
        self.config = config
        self.config_dir = config_dir

        self.mcws: Optional[MCWSClient] = None
        self.bridge: Optional[BridgeController] = None
        self.discovery: Optional[CastDiscovery] = None
        self.server: Optional[CastServer] = None
        self.eureka: Optional[EurekaServer] = None
        self.jellyfin_player: Optional[JellyfinRemotePlayer] = None
        self.outward_manager: Optional[OutwardCastManager] = None

        self._running = False
        self._health_task: Optional[asyncio.Task] = None

        # Health state flags
        self.mcws_ok = False
        self.jellyfin_ok = False

        # Status change callback: callback(mcws_ok: bool, jellyfin_ok: bool, message: str)
        self.on_status_change: Optional[Callable[[bool, bool, str], None]] = None

    @property
    def is_running(self) -> bool:
        return self._running

    def _ensure_certs(self, cert_file: str, key_file: str) -> None:
        if os.path.isfile(cert_file) and os.path.isfile(key_file):
            return
        logger.info("Generating self-signed TLS certificate …")
        generate_self_signed_cert(cert_file, key_file)

    async def start(self) -> None:
        if self._running:
            return

        logger.info("Starting Bridge Service …")
        self._running = True

        # 1. JRiver MCWS client
        jcfg = self.config.get("jriver", {})
        self.mcws = MCWSClient(
            host=jcfg.get("host", "localhost"),
            port=int(jcfg.get("port", 52199)),
            username=jcfg.get("username"),
            password=jcfg.get("password"),
            zone=jcfg.get("zone"),
            use_ssl=bool(jcfg.get("use_ssl", False)),
        )

        # 2. Bridge controller
        url_rewrites: dict = self.config.get("url_rewrite", {}) or {}
        self.bridge = BridgeController(self.mcws, url_rewrites)

        # 3. Cast server & discovery
        ccfg = self.config.get("cast", {})
        device_name: str = ccfg.get("device_name", "JRiver Media Center")
        cast_port: int = int(ccfg.get("port", 8009))
        bind_addr: Optional[str] = ccfg.get("bind_address")
        status_interval: float = float(ccfg.get("status_interval", 1.0))
        cert_file: str = ccfg.get("cert_file", "certs/cast_bridge.crt")
        key_file: str = ccfg.get("key_file", "certs/cast_bridge.key")

        if not os.path.isabs(cert_file):
            cert_file = os.path.join(self.config_dir, cert_file)
        if not os.path.isabs(key_file):
            key_file = os.path.join(self.config_dir, key_file)

        self._ensure_certs(cert_file, key_file)

        self.discovery = CastDiscovery(
            device_name=device_name,
            port=cast_port,
            device_id=ccfg.get("device_id"),
            bind_address=bind_addr,
        )

        self.server = CastServer(
            cert_file=cert_file,
            key_file=key_file,
            bridge=self.bridge,
            device_name=device_name,
            host=bind_addr or "0.0.0.0",
            port=cast_port,
            status_interval=status_interval,
        )

        self.eureka = EurekaServer(
            device_name=device_name,
            host=bind_addr or "0.0.0.0",
            port=int(ccfg.get("eureka_port", 8008)),
        )

        # 4. Jellyfin player
        jellyfin_cfg = self.config.get("jellyfin", {})
        if jellyfin_cfg and jellyfin_cfg.get("url"):
            # Ensure persistent device_id across re-enables and restarts
            dev_id = jellyfin_cfg.get("device_id") or "jriver-bridge-permanent-id"
            self.jellyfin_player = JellyfinRemotePlayer(
                server_url=jellyfin_cfg["url"],
                bridge=self.bridge,
                device_name=jellyfin_cfg.get("device_name", device_name),
                username=jellyfin_cfg.get("username"),
                password=jellyfin_cfg.get("password"),
                api_key=jellyfin_cfg.get("api_key"),
                device_id=dev_id,
            )

        # Start components
        await self.discovery.start()
        await self.eureka.start()
        if self.jellyfin_player:
            await self.jellyfin_player.start()
        await self.server.start()

        # 5. Outward Cast manager (JRiver -> Chromecast)
        outward_cfg = self.config.get("outward_cast", {})
        if outward_cfg.get("enabled", False):
            self.outward_manager = OutwardCastManager(
                config=self.config,
                aiozc=self.discovery.aiozc if self.discovery else None,
                own_device_id=self.discovery.device_id if self.discovery else None,
            )
            await self.outward_manager.start()

        # Perform initial health check immediately on startup
        jr, jf = await self.check_health()
        status_msg = f"JRiver: {'OK' if jr else 'Offline'} | Jellyfin: {'OK' if jf else 'Offline'}"
        self._notify_status(status_msg)

        # Start background health check monitor
        self._health_task = asyncio.create_task(self._health_monitor_loop())
        logger.info("Bridge Service started successfully ✓")

    async def stop(self) -> None:
        if not self._running:
            return

        logger.info("Stopping Bridge Service …")
        self._running = False

        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except (asyncio.CancelledError, Exception):
                pass
            self._health_task = None

        if self.jellyfin_player:
            await self.jellyfin_player.stop()
            self.jellyfin_player = None

        if self.outward_manager:
            await self.outward_manager.stop()
            self.outward_manager = None

        if self.eureka:
            await self.eureka.stop()
            self.eureka = None

        if self.discovery:
            await self.discovery.stop()
            self.discovery = None

        if self.server:
            await self.server.stop()
            self.server = None

        if self.mcws:
            await self.mcws.close()
            self.mcws = None

        self.mcws_ok = False
        self.jellyfin_ok = False
        self._notify_status("Bridge disabled / stopped")
        logger.info("Bridge Service stopped ✓")

    async def check_health(self) -> tuple[bool, bool]:
        """Perform an immediate health check of JRiver and Jellyfin."""
        jriver_alive = False
        jellyfin_alive = False

        if self.mcws:
            try:
                jriver_alive = await self.mcws.alive()
            except Exception:
                jriver_alive = False

        if self.jellyfin_player and self.jellyfin_player.token:
            jellyfin_alive = True
        elif self.config.get("jellyfin", {}).get("url"):
            # Check basic reachability
            try:
                import aiohttp
                url = f"{self.config['jellyfin']['url'].rstrip('/')}/System/Info/Public"
                async with aiohttp.ClientSession() as s:
                    async with s.get(url, timeout=aiohttp.ClientTimeout(total=4)) as r:
                        jellyfin_alive = (r.status == 200)
            except Exception:
                jellyfin_alive = False

        self.mcws_ok = jriver_alive
        self.jellyfin_ok = jellyfin_alive
        return jriver_alive, jellyfin_alive

    async def _health_monitor_loop(self) -> None:
        """Poll health every 8 seconds and notify callback of state changes."""
        while self._running:
            try:
                jr, jf = await self.check_health()
                status_parts = []
                status_parts.append(f"JRiver: {'OK' if jr else 'Offline'}")
                status_parts.append(f"Jellyfin: {'OK' if jf else 'Offline'}")
                msg = " | ".join(status_parts)
                self._notify_status(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Health check error: %s", e)

            await asyncio.sleep(8)

    def _notify_status(self, msg: str) -> None:
        if self.on_status_change:
            try:
                self.on_status_change(self.mcws_ok, self.jellyfin_ok, msg)
            except Exception:
                pass
