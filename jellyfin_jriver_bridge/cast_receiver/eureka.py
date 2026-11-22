"""
HTTP Eureka Setup Service on port 8008.

Chromecast senders (including Chrome and Android) send HTTP requests to
port 8008 to query device metadata during discovery:
    GET /setup/eureka_info
    GET /setup/icon.png
"""

from __future__ import annotations

import logging
from typing import Optional

from aiohttp import web

logger = logging.getLogger(__name__)


class EurekaServer:
    """Lightweight HTTP server on port 8008 serving Eureka setup info."""

    def __init__(
        self,
        device_name: str,
        host: str = "0.0.0.0",
        port: int = 8008,
    ):
        self.device_name = device_name
        self.host = host
        self.port = port
        self.app = web.Application()
        self.app.router.add_get("/setup/eureka_info", self._handle_eureka_info)
        self.app.router.add_get("/setup/icon.png", self._handle_icon)
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None

    async def _handle_eureka_info(self, request: web.Request) -> web.Response:
        data = {
            "bssid": "fa:8f:ca:8f:ca:8f",
            "build_info": {
                "build_type": 2,
                "cast_build_revision": "1.56.281627",
                "cast_control_version": 1,
                "preview_channel_state": 1,
                "release_track": "stable-channel",
                "system_build_number": "281627",
            },
            "detail": {
                "icon_list": [],
            },
            "device_info": {
                "cloud_device_id": "0000000000000000",
                "factory_country_code": "US",
                "hotspot_bssid": "fa:8f:ca:8f:ca:8f",
                "mac_address": "FA:8F:CA:8F:CA:8F",
                "manufacturer": "Google Inc.",
                "model_name": "Eureka Dongle",
                "product_name": "Chromecast",
                "ssdp_udn": "uuid:00000000-0000-0000-0000-000000000000",
                "uma_client_id": "00000000-0000-0000-0000-000000000000",
            },
            "name": self.device_name,
            "net": {
                "ip_v4_address": request.host.split(":")[0],
            },
            "opt_in": {
                "crash": False,
                "device_analytics": False,
                "stats": False,
            },
            "setup": {
                "setup_state": 60,
            },
            "version": 8,
        }
        return web.json_response(data, headers={"Access-Control-Allow-Origin": "*"})

    async def _handle_icon(self, request: web.Request) -> web.Response:
        # Minimal 1x1 transparent PNG
        png_1x1 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00"
            b"\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return web.Response(body=png_1x1, content_type="image/png")

    async def start(self) -> None:
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        try:
            await self._site.start()
            logger.info("Eureka HTTP service listening on http://%s:%d", self.host, self.port)
        except Exception as e:
            logger.warning("Could not start Eureka HTTP service on port %d: %s", self.port, e)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            logger.info("Eureka HTTP service stopped")
