"""
TLS server that accepts Google Cast V2 connections on port 8009.

Chromecast devices listen on TCP/8009 with a self-signed TLS certificate.
Cast senders do **not** verify the server certificate, so any self-signed
cert is fine.

For each accepted connection, a :class:`CastConnection` is created which
reads framed protobuf messages and routes them through the
:class:`NamespaceRouter` to the :class:`BridgeController`.

A background task periodically broadcasts ``MEDIA_STATUS`` to all
connected senders so their UI stays in sync with JRiver's playback state.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from typing import TYPE_CHECKING, Optional

from .connection import CastConnection
from .namespaces import NamespaceRouter

if TYPE_CHECKING:
    from ..bridge.controller import BridgeController

logger = logging.getLogger(__name__)


class CastServer:
    """Async TLS server for the Cast V2 protocol."""

    def __init__(
        self,
        cert_file: str,
        key_file: str,
        bridge: BridgeController,
        device_name: str,
        host: str = "0.0.0.0",
        port: int = 8009,
        status_interval: float = 1.0,
    ):
        self.cert_file = cert_file
        self.key_file = key_file
        self.host = host
        self.port = port
        self.status_interval = status_interval

        self.router = NamespaceRouter(bridge, device_name)
        self._server: Optional[asyncio.AbstractServer] = None
        self._status_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # TLS context
    # ------------------------------------------------------------------

    def _create_ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.cert_file, self.key_file)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        # Chrome Cast SDK speaks TLS 1.2+
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx

    # ------------------------------------------------------------------
    # Connection callback
    # ------------------------------------------------------------------

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        conn = CastConnection(reader, writer, self.router)
        await conn.handle()

    # ------------------------------------------------------------------
    # Periodic status push
    # ------------------------------------------------------------------

    async def _periodic_status_broadcast(self) -> None:
        """Push ``MEDIA_STATUS`` to every connected sender at a fixed interval."""
        while True:
            await asyncio.sleep(self.status_interval)
            try:
                if self.router.connections and self.router.app_launched:
                    await self.router.broadcast_media_status()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.debug("Status broadcast error", exc_info=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start listening on the TLS socket."""
        ssl_ctx = self._create_ssl_context()

        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
            ssl=ssl_ctx,
        )

        self._status_task = asyncio.create_task(self._periodic_status_broadcast())

        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets)
        logger.info("Cast V2 TLS server listening on %s", addrs)

    async def serve_forever(self) -> None:
        if self._server:
            try:
                async with self._server:
                    await self._server.serve_forever()
            except asyncio.CancelledError:
                pass

    async def stop(self) -> None:
        if self._status_task:
            self._status_task.cancel()
            try:
                await self._status_task
            except (asyncio.CancelledError, Exception):
                pass
            self._status_task = None

        # Cleanly close all active client connections
        for conn in list(self.router.connections.values()):
            try:
                conn.writer.close()
            except Exception:
                pass
        self.router.connections.clear()

        if self._server:
            self._server.close()
            try:
                await self._server.wait_closed()
            except (asyncio.CancelledError, Exception):
                pass
            self._server = None

        logger.info("Cast server stopped")
