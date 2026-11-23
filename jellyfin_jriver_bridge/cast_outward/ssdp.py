"""
Simple Service Discovery Protocol (SSDP) Responder.

Listens for M-SEARCH discovery broadcasts on UDP 239.255.255.250:1900 and responds
with UPnP MediaRenderer:1 advertisements pointing JRiver Media Center to our
virtual renderer HTTP endpoints.
"""

from __future__ import annotations

import asyncio
from email.utils import formatdate
import logging
import socket
import struct
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900


class SSDPDeviceRecord:
    """Registration record for a virtual UPnP MediaRenderer."""

    def __init__(
        self,
        udn: str,
        friendly_name: str,
        location_url: str,
    ) -> None:
        self.udn = udn  # e.g. "uuid:jcast-xxxx"
        self.friendly_name = friendly_name
        self.location_url = location_url

    def get_targets(self) -> List[tuple[str, str]]:
        """Return (ST, USN) pairs for UPnP MediaRenderer advertisements."""
        return [
            ("upnp:rootdevice", f"{self.udn}::upnp:rootdevice"),
            (self.udn, self.udn),
            (
                "urn:schemas-upnp-org:device:MediaRenderer:1",
                f"{self.udn}::urn:schemas-upnp-org:device:MediaRenderer:1",
            ),
            (
                "urn:schemas-upnp-org:service:RenderingControl:1",
                f"{self.udn}::urn:schemas-upnp-org:service:RenderingControl:1",
            ),
            (
                "urn:schemas-upnp-org:service:AVTransport:1",
                f"{self.udn}::urn:schemas-upnp-org:service:AVTransport:1",
            ),
            (
                "urn:schemas-upnp-org:service:ConnectionManager:1",
                f"{self.udn}::urn:schemas-upnp-org:service:ConnectionManager:1",
            ),
        ]


class SSDPServer:
    """Async UDP multicast server for SSDP M-SEARCH and NOTIFY messages."""

    def __init__(self, bind_ip: str = "0.0.0.0") -> None:
        self.bind_ip = bind_ip
        self._devices: Dict[str, SSDPDeviceRecord] = {}  # udn -> record
        self._sock: Optional[socket.socket] = None
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._running = False
        self._notify_task: Optional[asyncio.Task] = None

    def register_device(self, record: SSDPDeviceRecord) -> None:
        """Register a virtual UPnP device to be advertised."""
        self._devices[record.udn] = record
        logger.info("SSDP registered virtual UPnP zone: %s (%s)", record.friendly_name, record.location_url)
        self.broadcast_alive(record)

    def unregister_device(self, udn: str) -> None:
        """Unregister a virtual UPnP device and announce byebye."""
        record = self._devices.pop(udn, None)
        if record:
            self.broadcast_byebye(record)
            logger.info("SSDP unregistered virtual UPnP zone: %s", record.friendly_name)

    async def start(self) -> None:
        """Start listening for SSDP M-SEARCH broadcasts."""
        if self._running:
            return
        self._running = True

        loop = asyncio.get_running_loop()

        # Create dual unicast/multicast UDP socket with SO_REUSEADDR
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            # On Windows, bind to 0.0.0.0:1900
            sock.bind(("", SSDP_PORT))
        except Exception as e:
            logger.warning("Could not bind SSDP UDP port 1900: %s (Windows SSDP service may be active)", e)
            sock.close()
            return

        # Join the SSDP multicast group
        try:
            mreq = struct.pack(
                "4s4s",
                socket.inet_aton(SSDP_ADDR),
                socket.inet_aton("0.0.0.0"),
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            # Set multicast TTL to 4 (LAN scope)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
        except Exception as e:
            logger.debug("Multicast membership note: %s", e)

        self._sock = sock

        class SSDPProtocol(asyncio.DatagramProtocol):
            def __init__(self, server: SSDPServer) -> None:
                self.server = server

            def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
                self.server._on_datagram_received(data, addr)

        try:
            transport, _ = await loop.create_datagram_endpoint(
                lambda: SSDPProtocol(self),
                sock=self._sock,
            )
            self._transport = transport
            logger.info("SSDP discovery responder active on UDP :1900 ✓")
        except Exception as e:
            logger.warning("Failed to initialize SSDP datagram endpoint: %s", e)
            return

        self._notify_task = asyncio.create_task(self._periodic_alive_loop())

    async def stop(self) -> None:
        """Stop SSDP server and send byebye notifications for all devices."""
        if not self._running:
            return
        self._running = False

        if self._notify_task:
            self._notify_task.cancel()
            self._notify_task = None

        for record in list(self._devices.values()):
            self.broadcast_byebye(record)

        if self._transport:
            self._transport.close()
            self._transport = None
        if self._sock:
            self._sock.close()
            self._sock = None

        self._devices.clear()
        logger.info("SSDP server stopped.")

    def _on_datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            text = data.decode("utf-8", "ignore")
        except Exception:
            return

        lines = text.split("\r\n")
        if not lines:
            return

        first_line = lines[0].strip()
        if not first_line.startswith("M-SEARCH"):
            return

        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().upper()] = v.strip()

        st = headers.get("ST", "")
        man = headers.get("MAN", "").strip('"')

        if man != "ssdp:discover":
            return

        # Reply with matches for our registered virtual renderers
        for record in self._devices.values():
            targets = record.get_targets()
            for target_st, usn in targets:
                if st == "ssdp:all" or st == target_st:
                    self._send_msearch_response(addr, target_st, usn, record.location_url)

    def _send_msearch_response(
        self, addr: tuple[str, int], st: str, usn: str, location: str
    ) -> None:
        date_str = formatdate(timeval=None, localtime=False, usegmt=True)
        response = (
            "HTTP/1.1 200 OK\r\n"
            "CACHE-CONTROL: max-age=1800\r\n"
            f"DATE: {date_str}\r\n"
            "EXT:\r\n"
            f"LOCATION: {location}\r\n"
            "SERVER: Windows/10.0 UPnP/1.0 JCastBridge/1.0\r\n"
            f"ST: {st}\r\n"
            f"USN: {usn}\r\n"
            "\r\n"
        )
        if self._transport:
            try:
                self._transport.sendto(response.encode("utf-8"), addr)
            except Exception:
                pass

    def broadcast_alive(self, record: SSDPDeviceRecord) -> None:
        """Send SSDP ssdp:alive multicast notification for a device."""
        if not self._transport:
            return
        for st, usn in record.get_targets():
            msg = (
                "NOTIFY * HTTP/1.1\r\n"
                f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
                "CACHE-CONTROL: max-age=1800\r\n"
                f"LOCATION: {record.location_url}\r\n"
                "NT: " + st + "\r\n"
                "NTS: ssdp:alive\r\n"
                "SERVER: Windows/10.0 UPnP/1.0 JCastBridge/1.0\r\n"
                f"USN: {usn}\r\n"
                "\r\n"
            )
            try:
                self._transport.sendto(msg.encode("utf-8"), (SSDP_ADDR, SSDP_PORT))
            except Exception:
                pass

    def broadcast_byebye(self, record: SSDPDeviceRecord) -> None:
        """Send SSDP ssdp:byebye multicast notification for a device."""
        if not self._transport:
            return
        for st, usn in record.get_targets():
            msg = (
                "NOTIFY * HTTP/1.1\r\n"
                f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
                "NT: " + st + "\r\n"
                "NTS: ssdp:byebye\r\n"
                f"USN: {usn}\r\n"
                "\r\n"
            )
            try:
                self._transport.sendto(msg.encode("utf-8"), (SSDP_ADDR, SSDP_PORT))
            except Exception:
                pass

    async def _periodic_alive_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(60.0)
                for record in list(self._devices.values()):
                    self.broadcast_alive(record)
            except asyncio.CancelledError:
                break
            except Exception:
                pass
