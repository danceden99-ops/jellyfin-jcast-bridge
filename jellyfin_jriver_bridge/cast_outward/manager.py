"""
Outward Cast Manager.

Coordinates Google Cast mDNS discovery, virtual UPnP/DLNA MediaRenderer
endpoints, and SSDP advertisements to present remote Cast audio/video targets
as native playback zones in JRiver Media Center.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import Dict, List, Optional

from zeroconf.asyncio import AsyncZeroconf

from .client import ChromecastClient
from .discovery import DiscoveredCastDevice, OutwardCastBrowser
from .ssdp import SSDPDeviceRecord, SSDPServer
from .upnp_renderer import VirtualRendererDevice, VirtualUPnPService

logger = logging.getLogger(__name__)


def _detect_lan_ip() -> str:
    """Best-effort detection of local LAN IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


class OutwardCastManager:
    """Manages the full lifecycle of outward casting (JRiver -> Chromecast)."""

    def __init__(
        self,
        config: dict,
        aiozc: Optional[AsyncZeroconf] = None,
        own_device_id: Optional[str] = None,
    ) -> None:
        self.config = config.get("outward_cast", {}) or {}
        self.enabled = bool(self.config.get("enabled", False))
        self.upnp_port = int(self.config.get("upnp_port", self.config.get("upnp_base_port", 8010)))
        self.zone_name_format = str(self.config.get("zone_name_format", "{name} [Cast]"))
        self.include_devices: List[str] = [
            d.lower() for d in (self.config.get("include_devices") or [])
        ]
        self.exclude_devices: List[str] = [
            d.lower() for d in (self.config.get("exclude_devices") or [])
        ]
        self.include_groups = bool(self.config.get("include_speaker_groups", True))
        self.bind_address = self.config.get("bind_address")

        self.lan_ip = self.bind_address or _detect_lan_ip()
        self.aiozc = aiozc
        self.own_device_id = own_device_id

        self.browser: Optional[OutwardCastBrowser] = None
        self.ssdp_server: Optional[SSDPServer] = None
        self.upnp_service: Optional[VirtualUPnPService] = None

        # Active virtual renderers: udn -> VirtualRendererDevice
        self.active_renderers: Dict[str, VirtualRendererDevice] = {}
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start outward casting subsystem if enabled."""
        if not self.enabled:
            logger.info("Outward casting (JRiver → Chromecast) is disabled in config.")
            return

        if self._running:
            return
        self._running = True

        logger.info("Initializing Outward Cast Manager (UPnP base port: %d) …", self.upnp_port)

        # 1. Start virtual UPnP HTTP service
        self.upnp_service = VirtualUPnPService(host=self.lan_ip, port=self.upnp_port)
        try:
            await self.upnp_service.start()
        except Exception as e:
            logger.error("Failed to start virtual UPnP service on port %d: %s", self.upnp_port, e)
            self._running = False
            return

        # 2. Start SSDP discovery responder
        self.ssdp_server = SSDPServer(bind_ip=self.lan_ip)
        await self.ssdp_server.start()

        # 3. Start mDNS Cast device browser
        self.browser = OutwardCastBrowser(
            aiozc=self.aiozc,
            on_device_added=self._on_cast_device_discovered,
            on_device_removed=self._on_cast_device_removed,
            own_device_id=self.own_device_id,
        )
        await self.browser.start()
        logger.info("Outward casting active: JRiver can now stream to Chromecast zones ✓")

    async def stop(self) -> None:
        """Stop browser, SSDP responder, UPnP HTTP server, and disconnect all clients."""
        if not self._running:
            return
        self._running = False

        if self.browser:
            await self.browser.stop()
            self.browser = None

        if self.ssdp_server:
            await self.ssdp_server.stop()
            self.ssdp_server = None

        if self.upnp_service:
            await self.upnp_service.stop()
            self.upnp_service = None

        for renderer in self.active_renderers.values():
            asyncio.create_task(renderer.cast_client.disconnect())

        self.active_renderers.clear()
        logger.info("Outward Cast Manager stopped.")

    # ------------------------------------------------------------------
    # Internal Event Handlers
    # ------------------------------------------------------------------

    def _should_include_device(self, device: DiscoveredCastDevice) -> bool:
        """Check user whitelist/blacklist rules for discovered devices."""
        fn_lower = device.friendly_name.strip().lower()

        if device.is_group and not self.include_groups:
            logger.debug("Skipping speaker group '%s' (include_speaker_groups=false)", device.friendly_name)
            return False

        if self.exclude_devices and any(ex in fn_lower for ex in self.exclude_devices):
            logger.debug("Skipping excluded Cast device: '%s'", device.friendly_name)
            return False

        if self.include_devices:
            if not any(inc in fn_lower for inc in self.include_devices):
                logger.debug("Skipping Cast device not in whitelist: '%s'", device.friendly_name)
                return False

        return True

    def _on_cast_device_discovered(self, device: DiscoveredCastDevice) -> None:
        if not self._running or not self.upnp_service or not self.ssdp_server:
            return

        if not self._should_include_device(device):
            return

        udn = device.udn
        if udn in self.active_renderers:
            # Device already registered
            return

        zone_name = self.zone_name_format.format(name=device.friendly_name)
        device_key = device.device_id.replace("-", "")[:16].lower()

        client = ChromecastClient(host=device.host, port=device.port, name=device.friendly_name)

        renderer = VirtualRendererDevice(
            device_key=device_key,
            friendly_name=zone_name,
            udn=udn,
            cast_client=client,
        )

        self.active_renderers[udn] = renderer
        self.upnp_service.add_device(renderer)

        location_url = f"http://{self.lan_ip}:{self.upnp_port}/{device_key}/description.xml"
        ssdp_record = SSDPDeviceRecord(
            udn=udn,
            friendly_name=zone_name,
            location_url=location_url,
        )
        self.ssdp_server.register_device(ssdp_record)
        logger.info("Exposed Chromecast '%s' as JRiver Zone: '%s'", device.friendly_name, zone_name)

    def _on_cast_device_removed(self, udn: str) -> None:
        if not self._running or not self.upnp_service or not self.ssdp_server:
            return

        renderer = self.active_renderers.pop(udn, None)
        if renderer:
            self.ssdp_server.unregister_device(udn)
            self.upnp_service.remove_device(renderer.device_key)
            asyncio.create_task(renderer.cast_client.disconnect())
            logger.info("Removed JRiver Zone for Cast device: '%s'", renderer.friendly_name)
