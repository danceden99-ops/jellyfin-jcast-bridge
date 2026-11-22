"""
Bridge controller — translates Cast media commands into MCWS calls.

This is the glue layer between the Cast V2 namespace handlers and the
JRiver MCWS client.  It maintains minimal local state (current content ID,
volume, mute) so that Cast status responses can be assembled even when
JRiver hasn't started playing yet.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from ..jriver.mcws import MCWSClient

logger = logging.getLogger(__name__)


class BridgeController:
    """Map Cast playback verbs to JRiver MCWS endpoints."""

    def __init__(
        self,
        mcws: MCWSClient,
        url_rewrite_rules: Optional[Dict[str, str]] = None,
    ):
        self.mcws = mcws
        self._rewrites = url_rewrite_rules or {}

        # Shadow state — updated eagerly so Cast responses are immediate.
        self._content_id: Optional[str] = None
        self._content_type: str = "video/mp4"
        self._volume: float = 1.0
        self._muted: bool = False

    # ------------------------------------------------------------------
    # URL rewriting
    # ------------------------------------------------------------------

    def _rewrite_url(self, url: str) -> str:
        """Apply user-configured find→replace rules to media URLs."""
        for pattern, replacement in self._rewrites.items():
            url = url.replace(pattern, replacement)
        return url

    # ------------------------------------------------------------------
    # Cast → MCWS verbs
    # ------------------------------------------------------------------

    async def load(
        self,
        content_id: str,
        content_type: str,
        autoplay: bool,
        start_time: float,
        fallback_url: Optional[str] = None,
    ) -> None:
        self._content_id = content_id
        self._content_type = content_type

        url = self._rewrite_url(content_id)
        logger.info("Bridge LOAD → MCWS: %s", url[:150])

        ok = await self.mcws.play_url(url)
        if not ok and fallback_url:
            fb = self._rewrite_url(fallback_url)
            logger.info("Retrying with fallback stream URL: %s", fb[:150])
            ok = await self.mcws.play_url(fb)

        if ok and start_time > 0:
            await asyncio.sleep(0.8)
            await self.mcws.seek(int(start_time * 1000))
        if ok and not autoplay:
            await self.mcws.pause()

    async def play(self) -> None:
        info = await self.mcws.get_playback_info()
        logger.info("Bridge PLAY requested (current JRiver state: %s)", info["state"])
        if info["state"] == "PAUSED":
            await self.mcws.pause()  # MCWS Pause endpoint toggles
        elif info["state"] == "IDLE" and self._content_id:
            # Re-trigger play if stopped
            await self.mcws.play_url(self._content_id)

    async def pause(self) -> None:
        info = await self.mcws.get_playback_info()
        logger.info("Bridge PAUSE requested (current JRiver state: %s)", info["state"])
        # MCWS Playback/Pause toggles pause. If playing, toggling pauses it.
        # If state detection is ambiguous or delayed, call Playback/Pause directly.
        if info["state"] == "PLAYING" or info["state"] == "IDLE":
            await self.mcws.pause()

    async def toggle_play_pause(self) -> None:
        logger.info("Bridge TOGGLE PLAY/PAUSE requested")
        await self.mcws.pause()

    async def stop(self) -> None:
        logger.info("Bridge STOP requested")
        await self.mcws.stop()
        self._content_id = None

    async def seek(self, position_seconds: float) -> None:
        await self.mcws.seek(int(position_seconds * 1000))

    async def set_volume(self, level: float) -> None:
        self._volume = level
        await self.mcws.set_volume(level)

    async def set_muted(self, muted: bool) -> None:
        self._muted = muted
        await self.mcws.set_mute(muted)

    # ------------------------------------------------------------------
    # Status queries (used by namespace handlers for Cast responses)
    # ------------------------------------------------------------------

    async def get_volume_level(self) -> float:
        try:
            info = await self.mcws.get_playback_info()
            return info.get("volume", self._volume)
        except Exception:
            return self._volume

    async def get_muted(self) -> bool:
        return self._muted

    async def get_playback_status(self) -> Dict[str, Any]:
        """Return a dict suitable for building a Cast ``MEDIA_STATUS``."""
        try:
            info = await self.mcws.get_playback_info()
            return {
                "state": info["state"],
                "position": info["position"],
                "duration": info["duration"],
                "volume": info["volume"],
                "muted": self._muted,
                "content_id": self._content_id,
                "content_type": self._content_type,
            }
        except Exception:
            logger.debug("get_playback_status failed", exc_info=True)
            return {
                "state": "IDLE",
                "position": 0.0,
                "duration": 0.0,
                "volume": self._volume,
                "muted": self._muted,
                "content_id": self._content_id,
                "content_type": self._content_type,
            }
