"""
Cast V2 namespace handlers — connection, heartbeat, receiver, and media.

The Cast V2 protocol multiplexes several "channels" over a single TLS
connection.  Each channel is identified by a *namespace* URI.  This module
implements the four namespaces that every Cast sender expects:

* **connection** — ``CONNECT`` / ``CLOSE``
* **heartbeat** — ``PING`` / ``PONG``
* **receiver** — ``GET_STATUS``, ``LAUNCH``, ``STOP``
* **media** — ``LOAD``, ``PLAY``, ``PAUSE``, ``STOP``, ``SEEK``,
  ``SET_VOLUME``, ``GET_STATUS``

The :class:`NamespaceRouter` dispatches incoming messages by namespace and
forwards media commands to the :class:`BridgeController`.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Dict

from .protocol import CastMessage

if TYPE_CHECKING:
    from .connection import CastConnection
    from ..bridge.controller import BridgeController

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Namespace URIs
# ---------------------------------------------------------------------------

NS_CONNECTION  = "urn:x-cast:com.google.cast.tp.connection"
NS_HEARTBEAT   = "urn:x-cast:com.google.cast.tp.heartbeat"
NS_RECEIVER    = "urn:x-cast:com.google.cast.receiver"
NS_MEDIA       = "urn:x-cast:com.google.cast.media"
NS_DEVICE_AUTH = "urn:x-cast:com.google.cast.tp.deviceauth"

# Virtual transport / session identifiers for the "app" we pretend to run.
APP_TRANSPORT_ID = "web-1"
APP_SESSION_ID   = "jriver-bridge-session"

# Supported media commands bitmask (Pause | Seek | StreamVolume | StreamMute
# | SkipForward | SkipBackward | QueueNext).
SUPPORTED_MEDIA_COMMANDS = 0b0001_1111_1111  # 511


class NamespaceRouter:
    """Dispatch incoming Cast messages and manage per-connection state."""

    def __init__(self, bridge: BridgeController, device_name: str) -> None:
        self.bridge = bridge
        self.device_name = device_name

        # sender_id → CastConnection  (may contain several senders if
        # multiple browser tabs cast to us simultaneously)
        self.connections: Dict[str, CastConnection] = {}

        self.app_launched = False
        self.app_id: str | None = None
        self._media_session_id = 1

    # ------------------------------------------------------------------
    # Top-level dispatcher
    # ------------------------------------------------------------------

    async def handle_message(self, conn: CastConnection, msg: CastMessage) -> None:
        payload: dict = {}
        if msg.payload_utf8:
            try:
                payload = json.loads(msg.payload_utf8)
            except json.JSONDecodeError:
                logger.warning("Non-JSON payload on %s", msg.namespace)

        ns = msg.namespace
        if ns == NS_CONNECTION:
            await self._on_connection(conn, msg, payload)
        elif ns == NS_HEARTBEAT:
            await self._on_heartbeat(conn, msg, payload)
        elif ns == NS_RECEIVER:
            await self._on_receiver(conn, msg, payload)
        elif ns == NS_MEDIA:
            await self._on_media(conn, msg, payload)
        elif ns == NS_DEVICE_AUTH:
            await self._on_device_auth(conn, msg)
        else:
            logger.info("Received unhandled namespace %s from %s", ns, msg.source_id)

    # ------------------------------------------------------------------
    # Connection namespace
    # ------------------------------------------------------------------

    async def _on_connection(
        self, conn: CastConnection, msg: CastMessage, payload: dict
    ) -> None:
        msg_type = payload.get("type", "")
        if msg_type == "CONNECT":
            self.connections[msg.source_id] = conn
            logger.info("Sender %s connected", msg.source_id)
        elif msg_type == "CLOSE":
            self.connections.pop(msg.source_id, None)
            logger.info("Sender %s sent CLOSE", msg.source_id)

    # ------------------------------------------------------------------
    # Heartbeat namespace
    # ------------------------------------------------------------------

    async def _on_heartbeat(
        self, conn: CastConnection, msg: CastMessage, payload: dict
    ) -> None:
        if payload.get("type") == "PING":
            await conn.send_json(
                source_id=msg.destination_id,
                destination_id=msg.source_id,
                namespace=NS_HEARTBEAT,
                payload={"type": "PONG"},
            )

    # ------------------------------------------------------------------
    # Device Auth namespace
    # ------------------------------------------------------------------

    async def _on_device_auth(self, conn: CastConnection, msg: CastMessage) -> None:
        logger.info("Device auth challenge received from %s", msg.source_id)
        # DeviceAuthMessage with AuthError (error_type = INTERNAL_ERROR = 0)
        # Tag 3 (AuthError) length 2, Tag 1 (error_type) varint 0
        error_payload = bytes([0x1a, 0x02, 0x08, 0x00])
        response = CastMessage(
            source_id=msg.destination_id,
            destination_id=msg.source_id,
            namespace=NS_DEVICE_AUTH,
            payload_binary=error_payload,
        )
        await conn.send(response)

    # ------------------------------------------------------------------
    # Receiver namespace
    # ------------------------------------------------------------------

    async def _on_receiver(
        self, conn: CastConnection, msg: CastMessage, payload: dict
    ) -> None:
        msg_type = payload.get("type", "")
        req_id = payload.get("requestId", 0)

        if msg_type == "GET_STATUS":
            await self._send_receiver_status(conn, msg.source_id, req_id)

        elif msg_type == "LAUNCH":
            self.app_id = payload.get("appId", "CC1AD845")
            self.app_launched = True
            logger.info("LAUNCH app %s (treating as JRiver bridge)", self.app_id)
            await self._send_receiver_status(conn, msg.source_id, req_id)

        elif msg_type == "STOP":
            self.app_launched = False
            self.app_id = None
            await self.bridge.stop()
            await self._send_receiver_status(conn, msg.source_id, req_id)

        elif msg_type == "SET_VOLUME":
            volume = payload.get("volume", {})
            level = volume.get("level")
            muted = volume.get("muted")
            if level is not None:
                await self.bridge.set_volume(float(level))
            if muted is not None:
                await self.bridge.set_muted(bool(muted))
            await self._send_receiver_status(conn, msg.source_id, req_id)

    # ------------------------------------------------------------------
    # Media namespace
    # ------------------------------------------------------------------

    async def _on_media(
        self, conn: CastConnection, msg: CastMessage, payload: dict
    ) -> None:
        msg_type = payload.get("type", "")
        req_id = payload.get("requestId", 0)
        sender = msg.source_id

        if msg_type == "LOAD":
            media = payload.get("media", {})
            content_id = media.get("contentId", "")
            content_type = media.get("contentType", "video/mp4")
            stream_type = media.get("streamType", "BUFFERED")
            autoplay = payload.get("autoplay", True)
            current_time = payload.get("currentTime", 0)
            logger.info(
                "LOAD  url=%s  type=%s  autoplay=%s  t=%.1f",
                content_id[:120],
                content_type,
                autoplay,
                current_time,
            )
            await self.bridge.load(content_id, content_type, autoplay, current_time)
            await self._send_media_status(conn, sender, req_id)

        elif msg_type == "PLAY":
            await self.bridge.play()
            await self._send_media_status(conn, sender, req_id)

        elif msg_type == "PAUSE":
            await self.bridge.pause()
            await self._send_media_status(conn, sender, req_id)

        elif msg_type == "STOP":
            await self.bridge.stop()
            self._media_session_id += 1
            await self._send_media_status(conn, sender, req_id)

        elif msg_type == "SEEK":
            await self.bridge.seek(payload.get("currentTime", 0))
            await self._send_media_status(conn, sender, req_id)

        elif msg_type in ("SET_VOLUME", "VOLUME"):
            vol = payload.get("volume", {})
            if "level" in vol:
                await self.bridge.set_volume(float(vol["level"]))
            if "muted" in vol:
                await self.bridge.set_muted(bool(vol["muted"]))
            await self._send_media_status(conn, sender, req_id)

        elif msg_type == "GET_STATUS":
            await self._send_media_status(conn, sender, req_id)

        elif msg_type == "QUEUE_LOAD":
            # Jellyfin may send QUEUE_LOAD for playlist-style playback.
            # We treat the first item as a simple LOAD.
            items = payload.get("items", [])
            if items:
                media = items[0].get("media", {})
                content_id = media.get("contentId", "")
                content_type = media.get("contentType", "video/mp4")
                autoplay = items[0].get("autoplay", True)
                start_time = items[0].get("startTime", 0)
                logger.info("QUEUE_LOAD (first item) url=%s", content_id[:120])
                await self.bridge.load(content_id, content_type, autoplay, start_time)
            await self._send_media_status(conn, sender, req_id)

        else:
            logger.debug("Unhandled media type: %s", msg_type)
            await self._send_media_status(conn, sender, req_id)

    # ------------------------------------------------------------------
    # Status builders
    # ------------------------------------------------------------------

    async def _send_receiver_status(
        self, conn: CastConnection, dest_id: str, req_id: int
    ) -> None:
        """Build and send a ``RECEIVER_STATUS`` message."""
        apps: list[dict] = []
        if self.app_launched:
            apps.append(
                {
                    "appId": self.app_id or "CC1AD845",
                    "appType": "WEB",
                    "displayName": "JRiver Bridge",
                    "iconUrl": "",
                    "isIdleScreen": False,
                    "launchedFromCloud": False,
                    "namespaces": [
                        {"name": NS_CONNECTION},
                        {"name": NS_HEARTBEAT},
                        {"name": NS_MEDIA},
                        {"name": NS_RECEIVER},
                    ],
                    "sessionId": APP_SESSION_ID,
                    "statusText": "JRiver Media Center",
                    "transportId": APP_TRANSPORT_ID,
                    "universalAppId": self.app_id or "CC1AD845",
                }
            )

        volume_level = await self.bridge.get_volume_level()
        muted = await self.bridge.get_muted()

        await conn.send_json(
            source_id="receiver-0",
            destination_id=dest_id,
            namespace=NS_RECEIVER,
            payload={
                "type": "RECEIVER_STATUS",
                "requestId": req_id,
                "status": {
                    "applications": apps,
                    "isActiveInput": True,
                    "isStandBy": False,
                    "volume": {
                        "controlType": "attenuation",
                        "level": volume_level,
                        "muted": muted,
                        "stepInterval": 0.05,
                    },
                },
            },
        )

    async def _send_media_status(
        self, conn: CastConnection, dest_id: str, req_id: int
    ) -> None:
        """Build and send a ``MEDIA_STATUS`` message."""
        pb = await self.bridge.get_playback_status()

        entry: dict = {
            "mediaSessionId": self._media_session_id,
            "playbackRate": 1,
            "playerState": pb["state"],
            "currentTime": pb["position"],
            "supportedMediaCommands": SUPPORTED_MEDIA_COMMANDS,
            "volume": {
                "level": pb["volume"],
                "muted": pb["muted"],
            },
        }

        if pb.get("content_id"):
            entry["media"] = {
                "contentId": pb["content_id"],
                "contentType": pb.get("content_type", "video/mp4"),
                "streamType": "BUFFERED",
                "duration": pb["duration"],
            }

        await conn.send_json(
            source_id=APP_TRANSPORT_ID,
            destination_id=dest_id,
            namespace=NS_MEDIA,
            payload={
                "type": "MEDIA_STATUS",
                "requestId": req_id,
                "status": [entry],
            },
        )

    # ------------------------------------------------------------------
    # Broadcasting & cleanup
    # ------------------------------------------------------------------

    async def broadcast_media_status(self) -> None:
        """Send ``MEDIA_STATUS`` to every connected sender (periodic update)."""
        for sender_id, conn in list(self.connections.items()):
            try:
                await self._send_media_status(conn, sender_id, 0)
            except Exception:
                logger.debug("Status broadcast failed for %s", sender_id, exc_info=True)

    async def on_disconnect(self, conn: CastConnection) -> None:
        """Remove a connection's sender entries when the socket closes."""
        stale = [sid for sid, c in self.connections.items() if c is conn]
        for sid in stale:
            del self.connections[sid]
            logger.info("Cleaned up sender %s", sid)
