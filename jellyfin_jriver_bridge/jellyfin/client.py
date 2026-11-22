"""
Native Jellyfin Remote Control Client.

Connects directly to the Jellyfin server via REST and WebSocket as an active
player session. This exposes JRiver Media Center directly in the native
Jellyfin "Cast / Play On" menu across ALL clients (Web, iOS, Android, TV, Desktop)
without requiring Google hardware Cast device authentication.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

import aiohttp

if TYPE_CHECKING:
    from ..bridge.controller import BridgeController

logger = logging.getLogger(__name__)


class JellyfinRemotePlayer:
    """Connects to Jellyfin Server to register JRiver as a remote player target."""

    def __init__(
        self,
        server_url: str,
        bridge: BridgeController,
        device_name: str = "JRiver Media Center",
        username: Optional[str] = None,
        password: Optional[str] = None,
        api_key: Optional[str] = None,
        device_id: Optional[str] = None,
    ):
        self.server_url = server_url.rstrip("/")
        self.bridge = bridge
        self.device_name = device_name
        self.username = username
        self.password = password
        self.api_key = api_key
        self.device_id = device_id or f"jriver-bridge-{uuid.uuid4().hex[:12]}"

        self.token: Optional[str] = api_key
        self.user_id: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._running = False
        self._current_item_id: Optional[str] = None
        self._has_played: bool = False
        self._ws_task: Optional[asyncio.Task] = None
        self._progress_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # HTTP session & headers
    # ------------------------------------------------------------------

    def _auth_header(self) -> str:
        token_part = f', Token="{self.token}"' if self.token else ""
        return (
            f'MediaBrowser Client="JRiver Cast Bridge", '
            f'Device="{self.device_name}", '
            f'DeviceId="{self.device_id}", '
            f'Version="1.0.0"{token_part}'
        )

    def _headers(self) -> Dict[str, str]:
        auth = self._auth_header()
        headers = {
            "Authorization": auth,
            "X-Emby-Authorization": auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.token:
            headers["X-Emby-Token"] = self.token
        return headers

    def _ws_headers(self) -> Dict[str, str]:
        auth = self._auth_header()
        headers = {
            "Authorization": auth,
            "X-Emby-Authorization": auth,
        }
        if self.token:
            headers["X-Emby-Token"] = self.token
        return headers

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        return self._session

    # ------------------------------------------------------------------
    # Authentication & Capabilities
    # ------------------------------------------------------------------

    async def authenticate(self) -> bool:
        """Authenticate with the Jellyfin server if an API key is not supplied."""
        session = await self._get_session()

        # Step 1: Probe server info
        try:
            async with session.get(f"{self.server_url}/System/Info/Public") as resp:
                if resp.status == 200:
                    info = await resp.json()
                    logger.info(
                        "Jellyfin server '%s' (v%s) reachable at %s ✓",
                        info.get("ServerName", "Jellyfin"),
                        info.get("Version", "unknown"),
                        self.server_url,
                    )
                else:
                    logger.warning("Jellyfin /System/Info/Public returned HTTP %d", resp.status)
        except Exception as e:
            logger.error("Could not reach Jellyfin server at %s: %s", self.server_url, e)
            return False

        if self.token:
            logger.info("Using configured Jellyfin API token ✓")
            return True

        if not self.username:
            logger.warning("No Jellyfin username or API key configured — native Jellyfin client disabled.")
            return False

        url = f"{self.server_url}/Users/AuthenticateByName"
        payload = {
            "Username": self.username,
            "username": self.username,
            "Pw": self.password or "",
        }

        try:
            async with session.post(url, json=payload, headers=self._headers()) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(
                        "Jellyfin auth failed (HTTP %d): %s\n"
                        "  → Tip: Check your username and password, or generate an API key in "
                        "Jellyfin (Dashboard → API Keys) and add 'api_key: \"your_key\"' to config.yaml",
                        resp.status,
                        text.strip()[:200],
                    )
                    return False

                data = await resp.json()
                self.token = data.get("AccessToken")
                user = data.get("User", {})
                self.user_id = user.get("Id")
                logger.info("Authenticated to Jellyfin as user '%s' ✓", self.username)
                return True
        except Exception as e:
            logger.error("Error connecting to Jellyfin at %s: %s", self.server_url, e)
            return False

    async def report_capabilities(self) -> bool:
        """Tell Jellyfin this device supports playback remote control."""
        session = await self._get_session()
        # Endpoint: /Sessions/Capabilities/Full or /Sessions/Capabilities
        capabilities = {
            "PlayableMediaTypes": ["Video", "Audio"],
            "SupportsMediaControl": True,
            "SupportedCommands": [
                "Play",
                "Playstate",
                "PlayNext",
                "SetVolume",
                "Mute",
                "Unmute",
            ],
        }
        for path in ("Sessions/Capabilities/Full", "Sessions/Capabilities"):
            url = f"{self.server_url}/{path}"
            try:
                async with session.post(url, json=capabilities, headers=self._headers()) as resp:
                    if resp.status in (200, 204):
                        logger.info("Registered '%s' in Jellyfin Remote Control targets via /%s ✓", self.device_name, path)
                        return True
                    text = await resp.text()
                    logger.warning("/%s returned HTTP %d: %s", path, resp.status, text.strip()[:200])
            except Exception as e:
                logger.error("Failed to report capabilities to Jellyfin via /%s: %s", path, e)
        return False

    # ------------------------------------------------------------------
    # WebSocket Listener
    # ------------------------------------------------------------------

    async def _ws_keepalive_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Periodically ping Jellyfin to keep the WebSocket and remote session alive."""
        try:
            while self._running and not ws.closed:
                await asyncio.sleep(25.0)
                if not ws.closed:
                    await ws.send_str(json.dumps({"MessageType": "KeepAlive"}))
                    logger.debug("Sent periodic KeepAlive to Jellyfin WebSocket")
        except (asyncio.CancelledError, Exception):
            pass

    async def _ws_listen(self) -> None:
        """Maintain WebSocket connection to receive Play and Playstate commands."""
        session = await self._get_session()
        ws_base = self.server_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = (
            f"{ws_base}/socket?api_key={self.token}&token={self.token}"
            f"&deviceId={self.device_id}&device_id={self.device_id}"
        )

        while self._running:
            try:
                logger.info("Connecting to Jellyfin WebSocket: %s", ws_url)
                async with session.ws_connect(ws_url, headers=self._ws_headers()) as ws:
                    self._ws = ws
                    logger.info("Connected to Jellyfin WebSocket — ready for Cast commands ✓")

                    # Re-confirm capabilities on socket reconnect
                    await self.report_capabilities()

                    keepalive_task = asyncio.create_task(self._ws_keepalive_loop(ws))
                    try:
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self._handle_ws_message(msg.data)
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                    finally:
                        keepalive_task.cancel()
                        try:
                            await keepalive_task
                        except (asyncio.CancelledError, Exception):
                            pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Jellyfin WebSocket connection dropped: %s. Reconnecting in 5s...", e)
                await asyncio.sleep(5)

    async def _handle_ws_message(self, text: str) -> None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return

        msg_type = data.get("MessageType")
        if msg_type not in ("KeepAlive", "ForceKeepAlive"):
            logger.info("Jellyfin WS message received: %s", msg_type)
        else:
            logger.debug("Jellyfin WS message received: %s", msg_type)

        if msg_type == "ForceKeepAlive":
            if self._ws and not self._ws.closed:
                try:
                    await self._ws.send_str(json.dumps({"MessageType": "KeepAlive"}))
                    logger.debug("Replied to Jellyfin ForceKeepAlive ✓")
                except Exception as e:
                    logger.debug("Failed to reply to ForceKeepAlive: %s", e)
        elif msg_type == "KeepAlive":
            # Normal server heartbeat; no reply needed to prevent ping-pong loops
            pass
        elif msg_type == "Play":
            await self._on_play(data.get("Data", {}))
        elif msg_type == "Playstate":
            await self._on_playstate(data.get("Data", {}))
        elif msg_type == "GeneralCommand":
            await self._on_general_command(data.get("Data", {}))
        else:
            logger.debug("Unhandled Jellyfin WS MessageType: %s, data: %s", msg_type, data)

    # ------------------------------------------------------------------
    # Command Handlers
    # ------------------------------------------------------------------

    async def _get_item_info(self, item_id: str) -> Dict[str, Any]:
        session = await self._get_session()
        # Pass userId if available to ensure full item metadata permissions
        url = f"{self.server_url}/Users/{self.user_id}/Items/{item_id}" if self.user_id else f"{self.server_url}/Items/{item_id}"
        try:
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status == 200:
                    info = await resp.json()
                    logger.debug("Jellyfin item info retrieved: %s", info.get("Name"))
                    return info
                else:
                    # Fallback to /Items/{item_id}
                    async with session.get(f"{self.server_url}/Items/{item_id}", headers=self._headers()) as resp2:
                        if resp2.status == 200:
                            return await resp2.json()
                        logger.warning("Jellyfin get_item_info failed with HTTP %d", resp2.status)
        except Exception as e:
            logger.error("Error fetching item info from Jellyfin: %s", e)
        return {}

    async def _on_play(self, data: Dict[str, Any]) -> None:
        item_ids = data.get("ItemIds", [])
        if not item_ids:
            return

        item_id = item_ids[0]

        # If already playing another item, cleanly report stopped for the previous item
        if self._current_item_id and self._current_item_id != item_id:
            logger.info("Switching media: reporting previous item %s stopped", self._current_item_id)
            await self._report_stopped(self._current_item_id)

        self._current_item_id = item_id
        self._has_played = False
        start_ticks = data.get("StartPositionTicks", 0)
        start_seconds = start_ticks / 10_000_000.0

        item_info = await self._get_item_info(item_id)
        container = item_info.get("Container") or "mkv"
        media_type = item_info.get("MediaType", "Video")
        item_path = item_info.get("Path")

        logger.info(
            "Jellyfin item info: Name='%s', Container='%s', MediaType='%s', Path='%s'",
            item_info.get("Name"),
            container,
            media_type,
            item_path,
        )

        prefix = "Audio" if media_type == "Audio" else "Videos"
        stream_url = f"{self.server_url}/{prefix}/{item_id}/stream.{container}?static=true&api_key={self.token}"
        download_url = f"{self.server_url}/Items/{item_id}/Download?api_key={self.token}"

        # If a UNC or local path exists in Jellyfin and JRiver can access it, offer it as primary or fallback
        direct_file_path = item_path if (item_path and ("\\\\" in item_path or ":\\" in item_path)) else None
        primary_url = direct_file_path or stream_url
        fallback = stream_url if direct_file_path else download_url

        logger.info(
            "Jellyfin Cast: playing item %s [%s] (start=%.1fs) → JRiver MCWS (Target: %s)",
            item_id,
            container,
            start_seconds,
            primary_url,
        )
        await self.bridge.load(
            primary_url,
            "video/mp4",
            autoplay=True,
            start_time=start_seconds,
            fallback_url=fallback,
        )

        # Report playback started to Jellyfin
        await self._report_playing(item_id)

    async def _on_playstate(self, data: Dict[str, Any]) -> None:
        command = data.get("Command")
        logger.info("Jellyfin Cast command: %s (full data: %s)", command, data)

        if command in ("PlayPause", "play_pause"):
            await self.bridge.toggle_play_pause()
        elif command in ("Pause", "pause"):
            await self.bridge.pause()
        elif command in ("Unpause", "unpause", "Play", "play"):
            await self.bridge.play()
        elif command in ("Stop", "stop"):
            await self.bridge.stop()
            if self._current_item_id:
                await self._report_stopped(self._current_item_id)
                self._current_item_id = None
                self._has_played = False
        elif command in ("Seek", "seek"):
            seek_ticks = data.get("SeekPositionTicks", 0)
            await self.bridge.seek(seek_ticks / 10_000_000.0)
        else:
            # Fallback for any other variation of play/pause
            logger.info("Handling unmapped playstate command '%s' via toggle_play_pause", command)
            await self.bridge.toggle_play_pause()

    async def _on_general_command(self, data: Dict[str, Any]) -> None:
        name = data.get("Name")
        logger.info("Jellyfin GeneralCommand: %s (data: %s)", name, data)
        args = data.get("Arguments", {})
        if name in ("Stop", "stop"):
            await self.bridge.stop()
            if self._current_item_id:
                await self._report_stopped(self._current_item_id)
                self._current_item_id = None
                self._has_played = False
        elif name == "SetVolume":
            vol = float(args.get("Volume", 100)) / 100.0
            await self.bridge.set_volume(vol)
        elif name == "Mute":
            await self.bridge.set_muted(True)
        elif name == "Unmute":
            await self.bridge.set_muted(False)

    # ------------------------------------------------------------------
    # Jellyfin Progress Reporting
    # ------------------------------------------------------------------

    async def _report_playing(self, item_id: str) -> None:
        session = await self._get_session()
        url = f"{self.server_url}/Sessions/Playing"
        payload = {
            "ItemId": item_id,
            "PlayMethod": "DirectStream",
            "CanSeek": True,
        }
        try:
            async with session.post(url, json=payload, headers=self._headers()) as resp:
                logger.info("Reported playing to Jellyfin (ItemId: %s, HTTP %d)", item_id, resp.status)
        except Exception as e:
            logger.warning("Error reporting playing to Jellyfin: %s", e)

    async def _report_stopped(self, item_id: str) -> None:
        session = await self._get_session()
        url = f"{self.server_url}/Sessions/Playing/Stopped"
        info = await self.bridge.get_playback_status()
        payload = {
            "ItemId": item_id,
            "PositionTicks": int(info["position"] * 10_000_000),
        }
        try:
            async with session.post(url, json=payload, headers=self._headers()) as resp:
                logger.info("Reported stopped to Jellyfin (ItemId: %s, HTTP %d)", item_id, resp.status)
        except Exception as e:
            logger.warning("Error reporting stopped to Jellyfin: %s", e)

    async def _progress_loop(self) -> None:
        while self._running:
            await asyncio.sleep(1.0)
            if not self._current_item_id:
                continue
            try:
                info = await self.bridge.get_playback_status()

                # Track when JRiver actively starts rendering/playing
                # Notice: In JRiver, when a file is open, PositionMS, DurationMS, or FileKey are populated!
                is_active = (info["state"] in ("PLAYING", "PAUSED")) or (info["position"] > 0)
                if is_active:
                    self._has_played = True

                # Only report stopped when JRiver is genuinely IDLE *after* having been active
                if self._has_played and info["state"] == "IDLE":
                    logger.info("JRiver playback stopped (IDLE) -> releasing Jellyfin session for item %s", self._current_item_id)
                    await self._report_stopped(self._current_item_id)
                    self._current_item_id = None
                    self._has_played = False
                    continue

                session = await self._get_session()
                url = f"{self.server_url}/Sessions/Playing/Progress"
                payload = {
                    "ItemId": self._current_item_id,
                    "PositionTicks": int(info["position"] * 10_000_000),
                    "IsPaused": info["state"] == "PAUSED",
                    "IsMuted": info["muted"],
                    "VolumeLevel": int(info["volume"] * 100),
                    "CanSeek": True,
                    "PlayMethod": "DirectStream",
                }
                async with session.post(url, json=payload, headers=self._headers()) as resp:
                    if resp.status not in (200, 204):
                        logger.warning("Sessions/Playing/Progress returned HTTP %d for item %s", resp.status, self._current_item_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Progress report exception: %s", e)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> bool:
        self._running = True
        if not await self.authenticate():
            return False

        # Register capabilities with Jellyfin immediately so JRiver appears as a player
        await self.report_capabilities()

        self._ws_task = asyncio.create_task(self._ws_listen())
        self._progress_task = asyncio.create_task(self._progress_loop())
        return True

    async def stop(self) -> None:
        self._running = False
        if self._progress_task:
            self._progress_task.cancel()
            try:
                await self._progress_task
            except (asyncio.CancelledError, Exception):
                pass
            self._progress_task = None
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except (asyncio.CancelledError, Exception):
                pass
            self._ws_task = None
        if self._ws and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._session and not self._session.closed:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None
        logger.info("Jellyfin remote player stopped")
