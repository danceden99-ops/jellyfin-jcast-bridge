"""
JRiver Media Center Web Service (MCWS) async HTTP client.

MCWS is an HTTP REST API that JRiver Media Center exposes (by default on
port 52199) to control playback, browse the library, and query device
state.  Every endpoint returns XML of the form::

    <Response Status="OK">
      <Item Name="key">value</Item>
      ...
    </Response>

This module wraps the playback-control endpoints that the bridge needs:

* ``Alive`` — connectivity check
* ``Playback/Zones`` — list zones
* ``Playback/Info`` — current state, position, duration, volume
* ``Playback/PlayByURL`` — play an arbitrary URL
* ``Playback/Pause`` — toggle pause
* ``Playback/Stop`` — stop
* ``Playback/Position`` — seek
* ``Playback/Volume`` — set volume
* ``Playback/Mute`` — set mute
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger(__name__)


class MCWSClient:
    """Async client for JRiver MCWS."""

    def __init__(
        self,
        host: str,
        port: int = 52199,
        username: Optional[str] = None,
        password: Optional[str] = None,
        zone: Optional[str] = None,
        use_ssl: bool = False,
    ):
        scheme = "https" if use_ssl else "http"
        self.base_url = f"{scheme}://{host}:{port}/MCWS/v1"
        self.auth = (
            aiohttp.BasicAuth(username, password)
            if username
            else None
        )
        self.zone = zone
        self.active_zone_id: Optional[str] = None
        self._playback_starting_time: float = 0.0
        self._session: Optional[aiohttp.ClientSession] = None

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self._session = aiohttp.ClientSession(
                auth=self.auth, timeout=timeout
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Low-level request + XML parse
    # ------------------------------------------------------------------

    async def _get(
        self, path: str, params: Optional[Dict[str, str]] = None, log_error: bool = True
    ) -> Optional[ET.Element]:
        session = await self._get_session()
        url = f"{self.base_url}/{path}"
        if params:
            url += "?" + urlencode(params)

        try:
            async with session.get(url, ssl=False) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    if log_error:
                        logger.error("MCWS %s → HTTP %d: %s", path, resp.status, text.strip()[:200])
                    else:
                        logger.debug("MCWS %s → HTTP %d (expected during fallback)", path, resp.status)
                    return None
                text = await resp.text()
                return ET.fromstring(text)
        except aiohttp.ClientError as exc:
            if log_error:
                logger.error("MCWS %s network error: %s", path, exc)
            return None
        except ET.ParseError as exc:
            if log_error:
                logger.error("MCWS %s XML parse error: %s", path, exc)
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _zone_params(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        params: Dict[str, str] = {}
        if self.zone is not None:
            params["Zone"] = str(self.zone)
            params["ZoneType"] = "ID" if str(self.zone).isdigit() else "Name"
        elif self.active_zone_id is not None:
            params["Zone"] = str(self.active_zone_id)
            params["ZoneType"] = "ID"
        else:
            # -1 targets the currently active/focused playback zone in JRiver
            params["Zone"] = "-1"
            params["ZoneType"] = "ID"
        if extra:
            params.update(extra)
        return params

    @staticmethod
    def _item(root: Optional[ET.Element], name: str, default: str = "") -> str:
        """Return the text of ``<Item Name="...">`` or *default*."""
        if root is None:
            return default
        for item in root.findall("Item"):
            if item.get("Name") == name:
                return item.text or default
        return default

    @staticmethod
    def _ok(root: Optional[ET.Element]) -> bool:
        return root is not None and root.get("Status") == "OK"

    # ------------------------------------------------------------------
    # Public endpoints
    # ------------------------------------------------------------------

    async def alive(self) -> bool:
        """Return ``True`` if MCWS responds to ``/Alive``."""
        return self._ok(await self._get("Alive"))

    async def get_zones(self) -> List[Dict[str, str]]:
        root = await self._get("Playback/Zones")
        if root is None:
            return []
        zones: List[Dict[str, str]] = []
        for item in root.findall("Item"):
            zones.append({"id": item.get("Name", ""), "name": item.text or ""})
        return zones

    # ── playback control ──────────────────────────────────────────────

    async def play_url(self, url: str) -> bool:
        """Start playing *url* in JRiver using all supported MCWS methods."""
        logger.info("MCWS: attempting playback of URL: %s", url)
        self._playback_starting_time = time.time()

        # Method 1: PlayByFilename with Filenames (JRiver accepts plural 'Filenames' for URLs)
        root = await self._get("Playback/PlayByFilename", self._zone_params({"Filenames": url}), log_error=False)
        if self._ok(root):
            logger.info("MCWS: playing via PlayByFilename (Filenames) ✓")
            return True

        # Method 2: PlayByFilename with Filename
        root = await self._get("Playback/PlayByFilename", self._zone_params({"Filename": url}), log_error=False)
        if self._ok(root):
            logger.info("MCWS: playing via PlayByFilename (Filename) ✓")
            return True

        # Method 3: Control/CommandLine with Arguments=/PlayReplace
        root = await self._get("Control/CommandLine", {"Arguments": f'/PlayReplace "{url}"'}, log_error=False)
        if self._ok(root):
            logger.info("MCWS: playing via Control/CommandLine (Arguments) ✓")
            return True

        # Method 4: Control/CommandLine with CommandLine=/PlayReplace
        root = await self._get("Control/CommandLine", {"CommandLine": f'/PlayReplace "{url}"'}, log_error=False)
        if self._ok(root):
            logger.info("MCWS: playing via Control/CommandLine (CommandLine) ✓")
            return True

        # Method 5: Playback/Play with Filename
        root = await self._get("Playback/Play", self._zone_params({"Filename": url}), log_error=False)
        if self._ok(root):
            logger.info("MCWS: playing via Playback/Play (Filename) ✓")
            return True

        logger.error("MCWS: all playback methods failed for URL: %s", url[:120])
        return False

    async def pause(self) -> bool:
        res = await self._get("Playback/Pause", self._zone_params())
        ok = self._ok(res)
        logger.info("MCWS Playback/Pause (zone=%s) → %s", self.active_zone_id or "-1", "OK" if ok else "FAILED")
        return ok

    async def play(self) -> bool:
        res = await self._get("Playback/Play", self._zone_params())
        ok = self._ok(res)
        logger.info("MCWS Playback/Play (zone=%s) → %s", self.active_zone_id or "-1", "OK" if ok else "FAILED")
        return ok

    async def unpause(self) -> bool:
        info = await self.get_playback_info()
        if info["state"] == "PAUSED":
            return await self.pause()
        return True

    async def stop(self) -> bool:
        res = await self._get("Playback/Stop", self._zone_params())
        ok = self._ok(res)
        logger.info("MCWS Playback/Stop (zone=%s) → %s", self.active_zone_id or "-1", "OK" if ok else "FAILED")
        # Send Escape to exit JRiver fullscreen display view back to UI
        await self._get("Control/Key", {"Key": "Escape"}, log_error=False)
        return ok

    async def seek(self, position_ms: int) -> bool:
        res = await self._get(
            "Playback/Position",
            self._zone_params({"Position": str(position_ms)}),
        )
        ok = self._ok(res)
        logger.info("MCWS Playback/Position (%d ms, zone=%s) → %s", position_ms, self.active_zone_id or "-1", "OK" if ok else "FAILED")
        return ok

    async def set_volume(self, level: float) -> bool:
        """Set volume.  *level* is 0.0 – 1.0."""
        return self._ok(
            await self._get(
                "Playback/Volume",
                self._zone_params({"Level": str(level)}),
            )
        )

    async def set_mute(self, muted: bool) -> bool:
        return self._ok(
            await self._get(
                "Playback/Mute",
                self._zone_params({"Set": "1" if muted else "0"}),
            )
        )

    # ── playback info ─────────────────────────────────────────────────

    async def get_playback_info(self) -> Dict[str, Any]:
        """
        Query ``Playback/Info`` and return a normalised dict::

            {
                "state":    "IDLE" | "PAUSED" | "PLAYING",
                "position": <float seconds>,
                "duration": <float seconds>,
                "volume":   <float 0–1>,
                "muted":    <bool>,
                "name":     <str>,
                "file_key": <str>,
            }
        """
        root = await self._get("Playback/Info", self._zone_params())
        if root is None:
            return self._idle_info()

        # Update active zone ID if reported by JRiver
        zone_id = self._item(root, "ZoneID", "") or self._item(root, "CurrentZoneID", "")
        if zone_id and zone_id != "-1":
            self.active_zone_id = zone_id

        state_code = int(self._item(root, "State", "0"))
        state_map = {0: "IDLE", 1: "PAUSED", 2: "PLAYING", 3: "IDLE"}
        state = state_map.get(state_code, "IDLE")

        position_ms = int(self._item(root, "PositionMS", "0"))
        duration_ms = int(self._item(root, "DurationMS", "0"))
        file_key = self._item(root, "FileKey", "")
        name = self._item(root, "Name", "")

        # Initial buffering fallback: If State is 0 (IDLE) within 12 seconds of playback launch,
        # but JRiver reports an active FileKey or DurationMS, JRiver is opening the stream filter graph.
        # After that window, State 0 is genuinely IDLE (user pressed stop or media completed).
        is_opening = (time.time() - self._playback_starting_time) < 12.0
        if state == "IDLE" and is_opening and (position_ms > 0 or file_key or duration_ms > 0):
            state = "PLAYING"

        # MCWS volume: a float where 1.0 = full, 0.0 = silent
        raw_vol = self._item(root, "Volume", "1.0")
        try:
            volume = max(0.0, min(1.0, float(raw_vol)))
        except ValueError:
            volume = 1.0

        return {
            "state": state,
            "position": position_ms / 1000.0,
            "duration": duration_ms / 1000.0,
            "volume": volume,
            "muted": False,
            "name": name,
            "file_key": file_key,
        }

    @staticmethod
    def _idle_info() -> Dict[str, Any]:
        return {
            "state": "IDLE",
            "position": 0.0,
            "duration": 0.0,
            "volume": 1.0,
            "muted": False,
            "name": "",
            "file_key": "",
        }
