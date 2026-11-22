"""
mDNS service advertisement — makes this bridge visible as a Chromecast device.

Chrome and other Google Cast senders discover receivers by browsing for
``_googlecast._tcp.local.`` via multicast DNS.  This module registers a
service record with the required TXT properties so that Jellyfin's web
client (which uses the Google Cast SDK) sees us in its device picker.
"""

from __future__ import annotations

import logging
import socket
import uuid
from typing import Optional

from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

logger = logging.getLogger(__name__)


class CastDiscovery:
    """Advertise the bridge as a Chromecast device on the local network."""

    SERVICE_TYPE = "_googlecast._tcp.local."

    def __init__(
        self,
        device_name: str,
        port: int = 8009,
        device_id: Optional[str] = None,
        bind_address: Optional[str] = None,
    ):
        self.device_name = device_name
        self.port = port
        self.device_id = device_id or uuid.uuid4().hex[:32]
        self.bind_address = bind_address
        self.aiozc: Optional[AsyncZeroconf] = None
        self.service_info: Optional[ServiceInfo] = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_local_ip() -> str:
        """Best-effort detection of the host's LAN IP address."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                # Connecting a UDP socket does *not* send traffic; the OS just
                # resolves the outbound interface so we can read the local IP.
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Register the mDNS service record."""
        local_ip = self.bind_address or self._detect_local_ip()

        # TXT record properties expected by Google Cast senders.
        properties: dict[str, str] = {
            "id": self.device_id,
            "cd": self.device_id[:8],
            "rm": "",
            "ve": "05",                       # protocol version
            "md": "Chromecast",               # model description (Chromecast for video)
            "ic": "/setup/icon.png",
            "fn": self.device_name,           # friendly name
            "ca": "4101",                     # capability flags (4101 = Video + Audio Out)
            "st": "0",                        # idle status
            "bs": "FA8FCA8FCA8F",
            "nf": "1",
            "rs": "",
        }

        # The service *name* must be unique on the network.
        safe_name = self.device_name.replace(" ", "-").replace(".", "")
        service_name = f"{safe_name}-{self.device_id[:8]}.{self.SERVICE_TYPE}"

        self.service_info = ServiceInfo(
            type_=self.SERVICE_TYPE,
            name=service_name,
            addresses=[socket.inet_aton(local_ip)],
            port=self.port,
            properties=properties,
            server=f"{safe_name}.local.",
        )

        self.aiozc = AsyncZeroconf()
        await self.aiozc.async_register_service(self.service_info)
        logger.info(
            "mDNS: advertising '%s' as a Cast device at %s:%s",
            self.device_name,
            local_ip,
            self.port,
        )

    async def stop(self) -> None:
        """Unregister the mDNS service."""
        if self.aiozc:
            if self.service_info:
                try:
                    await self.aiozc.async_unregister_service(self.service_info)
                except Exception:
                    pass
                self.service_info = None
            try:
                await self.aiozc.async_close()
            except Exception:
                pass
            self.aiozc = None
            logger.info("mDNS: stopped advertising")
