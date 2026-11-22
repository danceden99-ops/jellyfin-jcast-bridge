"""
Single Cast V2 client connection handler.

Each Chromecast sender (browser / app) opens **one** TLS connection to
port 8009.  Messages are framed with a 4-byte big-endian length prefix
followed by a serialised ``CastMessage`` protobuf.

This module reads those framed messages, decodes them, dispatches them
to the :class:`NamespaceRouter`, and provides helpers for sending
responses back to the sender.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
from typing import TYPE_CHECKING

from .protocol import CastMessage, decode_cast_message, frame_message

if TYPE_CHECKING:
    from .namespaces import NamespaceRouter

logger = logging.getLogger(__name__)

# Maximum single message size we're willing to accept (64 KiB).
_MAX_MESSAGE_SIZE = 65_536


class CastConnection:
    """Manages one TLS session with a Cast sender."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        router: NamespaceRouter,
    ):
        self.reader = reader
        self.writer = writer
        self.router = router
        self.peer = writer.get_extra_info("peername")
        self._closed = False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def handle(self) -> None:
        """Read messages until the connection drops or is closed."""
        logger.info("Cast connection opened from %s", self.peer)
        try:
            while not self._closed:
                # --- 4-byte length header ---
                header = await self.reader.readexactly(4)
                length = struct.unpack(">I", header)[0]

                if length > _MAX_MESSAGE_SIZE:
                    logger.warning(
                        "Dropping oversized message (%d bytes) from %s",
                        length,
                        self.peer,
                    )
                    break

                # --- message body ---
                data = await self.reader.readexactly(length)
                msg = decode_cast_message(data)

                _log_rx(msg)
                await self.router.handle_message(self, msg)

        except asyncio.IncompleteReadError:
            logger.info("Cast connection closed by peer %s", self.peer)
        except ConnectionResetError:
            logger.info("Cast connection reset by %s", self.peer)
        except Exception:
            logger.exception("Unexpected error on Cast connection from %s", self.peer)
        finally:
            await self.close()

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send(self, msg: CastMessage) -> None:
        """Send a framed CastMessage to the peer."""
        if self._closed:
            return
        self.writer.write(frame_message(msg))
        await self.writer.drain()
        _log_tx(msg)

    async def send_json(
        self,
        source_id: str,
        destination_id: str,
        namespace: str,
        payload: dict,
    ) -> None:
        """Convenience: build a CastMessage with a JSON string payload and send."""
        await self.send(
            CastMessage(
                source_id=source_id,
                destination_id=destination_id,
                namespace=namespace,
                payload_utf8=json.dumps(payload, separators=(",", ":")),
            )
        )

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except Exception:
            pass
        logger.info("Cast connection from %s closed", self.peer)
        await self.router.on_disconnect(self)


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _log_rx(msg: CastMessage) -> None:
    short_ns = msg.namespace.rsplit(".", 1)[-1]
    if short_ns == "heartbeat":
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("RX [heartbeat] %s → %s", msg.source_id, msg.destination_id)
        return
    payload_preview = (msg.payload_utf8 or "<binary>")[:300]
    logger.info(
        "RX [%s] %s → %s : %s",
        short_ns,
        msg.source_id,
        msg.destination_id,
        payload_preview,
    )


def _log_tx(msg: CastMessage) -> None:
    short_ns = msg.namespace.rsplit(".", 1)[-1]
    if short_ns == "heartbeat":
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("TX [heartbeat] %s → %s", msg.source_id, msg.destination_id)
        return
    payload_preview = (msg.payload_utf8 or "<binary>")[:300]
    logger.info(
        "TX [%s] %s → %s : %s",
        short_ns,
        msg.source_id,
        msg.destination_id,
        payload_preview,
    )
