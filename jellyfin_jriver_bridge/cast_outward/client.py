"""
Async Google Cast V2 Client (Sender).

Connects to a physical Chromecast, launches the Default Media Receiver (appId: CC1AD845),
sends playback verbs (LOAD, PLAY, PAUSE, SEEK, STOP, SET_VOLUME), maintains heartbeats,
and tracks real-time playback progress and state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from typing import Any, Callable, Dict, Optional

from ..cast_receiver.protocol import (
    CastMessage,
    decode_cast_message,
    frame_message,
    read_length_prefix,
)

logger = logging.getLogger(__name__)

NS_CONNECTION = "urn:x-cast:com.google.cast.tp.connection"
NS_HEARTBEAT = "urn:x-cast:com.google.cast.tp.heartbeat"
NS_RECEIVER = "urn:x-cast:com.google.cast.receiver"
NS_MEDIA = "urn:x-cast:com.google.cast.media"

DEFAULT_MEDIA_RECEIVER_APP_ID = "CC1AD845"
SOURCE_ID = "sender-jcast"
DESTINATION_RECEIVER = "receiver-0"


class ChromecastClient:
    """Async Cast V2 client connected to a single Chromecast receiver."""

    def __init__(self, host: str, port: int = 8009, name: str = "Chromecast") -> None:
        self.host = host
        self.port = port
        self.name = name

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._read_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        self._request_id = 1
        self._destination_transport_id: Optional[str] = None
        self._session_id: Optional[str] = None
        self._media_session_id: Optional[int] = None

        # State cache
        self.player_state = "STOPPED"  # STOPPED, PLAYING, PAUSED, BUFFERING
        self.current_time = 0.0
        self.duration = 0.0
        self.volume_level = 1.0
        self.is_muted = False
        self._state_updated_at = 0.0

        self.on_state_changed: Optional[Callable[[], None]] = None
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    def _next_req_id(self) -> int:
        req_id = self._request_id
        self._request_id += 1
        return req_id

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Establish TLS connection to the Chromecast device."""
        if self.is_connected:
            return True

        async with self._lock:
            try:
                ssl_ctx = ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE

                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port, ssl=ssl_ctx),
                    timeout=5.0,
                )

                # Connect to receiver-0
                await self._send_json(
                    NS_CONNECTION,
                    DESTINATION_RECEIVER,
                    {"type": "CONNECT", "userAgent": "JCastBridge/1.0"},
                )

                # Start reader and heartbeat tasks
                self._read_task = asyncio.create_task(self._read_loop())
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                # Request initial status
                await self._send_json(
                    NS_RECEIVER,
                    DESTINATION_RECEIVER,
                    {"type": "GET_STATUS", "requestId": self._next_req_id()},
                )

                logger.info("Connected to Cast device '%s' (%s:%d)", self.name, self.host, self.port)
                return True
            except Exception as e:
                logger.warning("Failed to connect to Cast device '%s' (%s:%d): %s", self.name, self.host, self.port, e)
                await self._cleanup()
                return False

    async def disconnect(self) -> None:
        """Disconnect and release resources."""
        async with self._lock:
            await self._cleanup()

    async def _cleanup(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._read_task:
            self._read_task.cancel()
            self._read_task = None
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._reader = None
        self._destination_transport_id = None
        self._media_session_id = None
        self.player_state = "STOPPED"

    # ------------------------------------------------------------------
    # Protocol I/O
    # ------------------------------------------------------------------

    async def _send_json(self, namespace: str, destination_id: str, payload: dict) -> None:
        if not self._writer or self._writer.is_closing():
            return
        msg = CastMessage(
            source_id=SOURCE_ID,
            destination_id=destination_id,
            namespace=namespace,
            payload_utf8=json.dumps(payload),
        )
        data = frame_message(msg)
        try:
            self._writer.write(data)
            await self._writer.drain()
        except Exception as e:
            logger.debug("Write error to '%s': %s", self.name, e)

    async def _read_loop(self) -> None:
        while True:
            try:
                if not self._reader:
                    break
                header = await self._reader.readexactly(4)
                length = read_length_prefix(header)
                if length > 65536:
                    logger.warning("Cast frame too large (%d bytes) from %s", length, self.name)
                    break
                body = await self._reader.readexactly(length)
                msg = decode_cast_message(body)
                await self._handle_incoming_message(msg)
            except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Read error from '%s': %s", self.name, e)
                break

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(5.0)
                await self._send_json(
                    NS_HEARTBEAT,
                    DESTINATION_RECEIVER,
                    {"type": "PING"},
                )
                if self._destination_transport_id:
                    await self._send_json(
                        NS_HEARTBEAT,
                        self._destination_transport_id,
                        {"type": "PING"},
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _handle_incoming_message(self, msg: CastMessage) -> None:
        if not msg.payload_utf8:
            return
        try:
            payload = json.loads(msg.payload_utf8)
        except Exception:
            return

        msg_type = payload.get("type", "")

        if msg.namespace == NS_HEARTBEAT:
            if msg_type == "PING":
                await self._send_json(NS_HEARTBEAT, msg.source_id, {"type": "PONG"})

        elif msg.namespace == NS_RECEIVER:
            if msg_type == "RECEIVER_STATUS":
                status = payload.get("status", {})
                volume = status.get("volume", {})
                if "level" in volume:
                    self.volume_level = float(volume["level"])
                if "muted" in volume:
                    self.is_muted = bool(volume["muted"])

                apps = status.get("applications", [])
                for app in apps:
                    if app.get("appId") == DEFAULT_MEDIA_RECEIVER_APP_ID:
                        transport_id = app.get("transportId")
                        if transport_id and transport_id != self._destination_transport_id:
                            self._destination_transport_id = transport_id
                            self._session_id = app.get("sessionId")
                            # Connect to the media transport
                            await self._send_json(
                                NS_CONNECTION,
                                transport_id,
                                {"type": "CONNECT", "userAgent": "JCastBridge/1.0"},
                            )
                            # Request media status
                            await self._send_json(
                                NS_MEDIA,
                                transport_id,
                                {"type": "GET_STATUS", "requestId": self._next_req_id()},
                            )

        elif msg.namespace == NS_MEDIA:
            if msg_type == "MEDIA_STATUS":
                statuses = payload.get("status", [])
                if statuses:
                    m_stat = statuses[0]
                    self._media_session_id = m_stat.get("mediaSessionId")
                    raw_state = m_stat.get("playerState", "IDLE")

                    # Map Cast state to UPnP standard state
                    if raw_state == "PLAYING":
                        self.player_state = "PLAYING"
                    elif raw_state == "PAUSED":
                        self.player_state = "PAUSED_PLAYBACK"
                    elif raw_state == "BUFFERING":
                        self.player_state = "TRANSITIONING"
                    else:
                        self.player_state = "STOPPED"

                    self.current_time = float(m_stat.get("currentTime", 0.0))
                    media = m_stat.get("media", {})
                    if "duration" in media:
                        self.duration = float(media["duration"])

                    if self.on_state_changed:
                        self.on_state_changed()

    # ------------------------------------------------------------------
    # High-level Media Verbs (invoked by UPnP renderer)
    # ------------------------------------------------------------------

    async def ensure_app_launched(self) -> bool:
        """Launch the Default Media Receiver if not currently running."""
        if not await self.connect():
            return False

        if self._destination_transport_id:
            return True

        req_id = self._next_req_id()
        await self._send_json(
            NS_RECEIVER,
            DESTINATION_RECEIVER,
            {
                "type": "LAUNCH",
                "appId": DEFAULT_MEDIA_RECEIVER_APP_ID,
                "requestId": req_id,
            },
        )

        # Wait up to 5 seconds for RECEIVER_STATUS with transportId
        for _ in range(25):
            await asyncio.sleep(0.2)
            if self._destination_transport_id:
                return True

        logger.warning("Timed out waiting for Default Media Receiver to launch on '%s'", self.name)
        return False

    async def load_media(
        self,
        content_id: str,
        content_type: str = "audio/flac",
        title: str = "",
        artist: str = "",
        album: str = "",
        autoplay: bool = True,
        current_time: float = 0.0,
    ) -> bool:
        """Load and stream a media URL on the Chromecast."""
        if not await self.ensure_app_launched():
            return False

        metadata: Dict[str, Any] = {"metadataType": 3}  # MusicTrackMediaMetadata
        if title:
            metadata["title"] = title
        if artist:
            metadata["artist"] = artist
        if album:
            metadata["albumName"] = album

        payload = {
            "type": "LOAD",
            "requestId": self._next_req_id(),
            "sessionId": self._session_id,
            "media": {
                "contentId": content_id,
                "streamType": "BUFFERED",
                "contentType": content_type,
                "metadata": metadata,
            },
            "autoplay": autoplay,
            "currentTime": current_time,
        }

        logger.info("Outward Cast LOAD on '%s': %s (%s)", self.name, content_id[:120], content_type)
        await self._send_json(NS_MEDIA, self._destination_transport_id, payload)
        self.player_state = "TRANSITIONING"
        return True

    async def play(self) -> None:
        """Resume playback."""
        if self._destination_transport_id and self._media_session_id is not None:
            await self._send_json(
                NS_MEDIA,
                self._destination_transport_id,
                {"type": "PLAY", "requestId": self._next_req_id(), "mediaSessionId": self._media_session_id},
            )
            self.player_state = "PLAYING"

    async def pause(self) -> None:
        """Pause playback."""
        if self._destination_transport_id and self._media_session_id is not None:
            await self._send_json(
                NS_MEDIA,
                self._destination_transport_id,
                {"type": "PAUSE", "requestId": self._next_req_id(), "mediaSessionId": self._media_session_id},
            )
            self.player_state = "PAUSED_PLAYBACK"

    async def stop(self) -> None:
        """Stop playback."""
        if self._destination_transport_id and self._media_session_id is not None:
            await self._send_json(
                NS_MEDIA,
                self._destination_transport_id,
                {"type": "STOP", "requestId": self._next_req_id(), "mediaSessionId": self._media_session_id},
            )
        self.player_state = "STOPPED"

    async def seek(self, position_seconds: float) -> None:
        """Seek to *position_seconds*."""
        if self._destination_transport_id and self._media_session_id is not None:
            await self._send_json(
                NS_MEDIA,
                self._destination_transport_id,
                {
                    "type": "SEEK",
                    "requestId": self._next_req_id(),
                    "mediaSessionId": self._media_session_id,
                    "currentTime": position_seconds,
                },
            )
            self.current_time = position_seconds

    async def set_volume(self, level: float) -> None:
        """Set volume level (0.0 to 1.0)."""
        level = max(0.0, min(1.0, level))
        self.volume_level = level
        await self._send_json(
            NS_RECEIVER,
            DESTINATION_RECEIVER,
            {
                "type": "SET_VOLUME",
                "requestId": self._next_req_id(),
                "volume": {"level": level},
            },
        )

    async def set_muted(self, muted: bool) -> None:
        """Set mute state."""
        self.is_muted = muted
        await self._send_json(
            NS_RECEIVER,
            DESTINATION_RECEIVER,
            {
                "type": "SET_VOLUME",
                "requestId": self._next_req_id(),
                "volume": {"muted": muted},
            },
        )
