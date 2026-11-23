"""
mDNS Discovery Browser for Google Cast Devices.

Browses the local network for ``_googlecast._tcp.local.`` services and notifies
the manager when Cast receivers (Google Nest, Chromecast Audio, Google TV,
or Speaker Groups) are added, updated, or removed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any, Callable, Dict, Optional

from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredCastDevice:
    """Represents a discovered Google Cast device on the local network."""

    service_name: str
    friendly_name: str
    model_name: str
    device_id: str
    host: str
    port: int
    is_group: bool = False

    @property
    def udn(self) -> str:
        """UPnP Unique Device Name identifier."""
        clean_id = self.device_id.replace("-", "")[:32]
        return f"uuid:jcast-{clean_id}"


class OutwardCastBrowser:
    """Browses for Google Cast devices via mDNS."""

    SERVICE_TYPE = "_googlecast._tcp.local."

    def __init__(
        self,
        aiozc: Optional[AsyncZeroconf] = None,
        on_device_added: Optional[Callable[[DiscoveredCastDevice], None]] = None,
        on_device_removed: Optional[Callable[[str], None]] = None,
        own_device_id: Optional[str] = None,
    ) -> None:
        self._aiozc = aiozc
        self._own_aiozc = False
        self._browser: Optional[AsyncServiceBrowser] = None
        self._devices: Dict[str, DiscoveredCastDevice] = {}  # service_name -> device
        self._on_added = on_device_added
        self._on_removed = on_device_removed
        self._own_device_id = own_device_id
        self._running = False

    @property
    def devices(self) -> Dict[str, DiscoveredCastDevice]:
        return dict(self._devices)

    async def start(self) -> None:
        """Start browsing for Google Cast devices."""
        if self._running:
            return
        self._running = True

        if self._aiozc is None:
            self._aiozc = AsyncZeroconf()
            self._own_aiozc = True

        logger.info("Starting mDNS browser for Google Cast devices …")
        self._browser = AsyncServiceBrowser(
            self._aiozc.zeroconf,
            self.SERVICE_TYPE,
            handlers=[self._on_service_state_change],
        )

    async def stop(self) -> None:
        """Stop browsing and clean up resources."""
        if not self._running:
            return
        self._running = False

        if self._browser:
            await self._browser.async_cancel()
            self._browser = None

        if self._own_aiozc and self._aiozc:
            await self._aiozc.async_close()
            self._aiozc = None

        self._devices.clear()
        logger.info("mDNS Google Cast browser stopped.")

    def _on_service_state_change(
        self,
        zeroconf: Any,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        """Callback from Zeroconf when a service changes state."""
        asyncio.create_task(self._handle_state_change(service_type, name, state_change))

    async def _handle_state_change(
        self, service_type: str, name: str, state_change: ServiceStateChange
    ) -> None:
        if not self._running or self._aiozc is None:
            return

        if state_change in (ServiceStateChange.Added, ServiceStateChange.Updated):
            info = AsyncServiceInfo(service_type, name)
            if not await info.async_request(self._aiozc.zeroconf, 3000):
                return

            addresses = info.parsed_addresses()
            if not addresses:
                return

            host = addresses[0]
            port = info.port or 8009

            # Parse TXT properties
            props: dict[str, str] = {}
            for k, v in info.properties.items():
                key_str = k.decode("utf-8", "ignore") if isinstance(k, bytes) else str(k)
                val_str = v.decode("utf-8", "ignore") if isinstance(v, bytes) else str(v)
                props[key_str] = val_str

            device_id = props.get("id") or name.split(".")[0]
            friendly_name = props.get("fn") or name.split(".")[0]
            model_name = props.get("md") or "Chromecast"

            # Ignore our own advertised inbound bridge receiver
            if self._own_device_id and (
                device_id == self._own_device_id
                or friendly_name == "JRiver Media Center"
            ):
                return

            is_group = (
                "group" in model_name.lower()
                or "group" in props.get("st", "").lower()
                or props.get("ca", "") == "0"
            )

            device = DiscoveredCastDevice(
                service_name=name,
                friendly_name=friendly_name,
                model_name=model_name,
                device_id=device_id,
                host=host,
                port=port,
                is_group=is_group,
            )

            is_new = name not in self._devices
            self._devices[name] = device
            logger.info(
                "Discovered Cast device: '%s' (%s at %s:%d) [group=%s]",
                friendly_name,
                model_name,
                host,
                port,
                is_group,
            )
            if self._on_added:
                self._on_added(device)

        elif state_change == ServiceStateChange.Removed:
            if name in self._devices:
                device = self._devices.pop(name)
                logger.info("Cast device removed: '%s' (%s)", device.friendly_name, name)
                if self._on_removed:
                    self._on_removed(device.udn)
