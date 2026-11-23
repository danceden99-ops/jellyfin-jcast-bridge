"""
Virtual UPnP MediaRenderer HTTP Server.

Presents discovered Google Cast devices as native UPnP/DLNA MediaRenderer zones
to JRiver Media Center. Handles UPnP XML device descriptions, SCPD service definitions,
and SOAP control endpoints for AVTransport and RenderingControl.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional
import xml.etree.ElementTree as ET

from aiohttp import web

from .client import ChromecastClient

logger = logging.getLogger(__name__)


def _seconds_to_time_str(seconds: float) -> str:
    """Convert float seconds to UPnP RelTime format HH:MM:SS."""
    if seconds < 0 or seconds != seconds:  # NaN check
        seconds = 0
    s = int(seconds)
    hours = s // 3600
    minutes = (s % 3600) // 60
    secs = s % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _time_str_to_seconds(time_str: str) -> float:
    """Convert HH:MM:SS string to seconds."""
    parts = time_str.strip().split(":")
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 1:
            return float(parts[0])
    except Exception:
        pass
    return 0.0


def _build_soap_response(action: str, service: str, body_content: str) -> str:
    """Build standard UPnP SOAP response envelope."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        "<s:Body>"
        f'<u:{action}Response xmlns:u="urn:schemas-upnp-org:service:{service}:1">'
        f"{body_content}"
        f"</u:{action}Response>"
        "</s:Body>"
        "</s:Envelope>"
    )


class VirtualRendererDevice:
    """State and descriptors for a single virtual UPnP MediaRenderer zone."""

    def __init__(
        self,
        device_key: str,
        friendly_name: str,
        udn: str,
        cast_client: ChromecastClient,
    ) -> None:
        self.device_key = device_key
        self.friendly_name = friendly_name
        self.udn = udn
        self.cast_client = cast_client

        # Active media tracking
        self.current_uri = ""
        self.current_metadata = ""
        self.title = ""
        self.artist = ""
        self.album = ""


class VirtualUPnPService:
    """HTTP server providing virtual UPnP endpoints for all active Cast targets."""

    def __init__(self, host: str, port: int = 8010) -> None:
        self.host = host
        self.port = port
        self.app = web.Application()
        self._devices: Dict[str, VirtualRendererDevice] = {}  # device_key -> device
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._setup_routes()

    def _setup_routes(self) -> None:
        self.app.router.add_get("/{device_key}/description.xml", self._handle_description)
        self.app.router.add_get("/{device_key}/{service}/scpd.xml", self._handle_scpd)
        self.app.router.add_post("/{device_key}/{service}/control", self._handle_control)

    def add_device(self, device: VirtualRendererDevice) -> None:
        self._devices[device.device_key] = device

    def remove_device(self, device_key: str) -> Optional[VirtualRendererDevice]:
        return self._devices.pop(device_key, None)

    def get_device(self, device_key: str) -> Optional[VirtualRendererDevice]:
        return self._devices.get(device_key)

    async def start(self) -> None:
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info("Virtual UPnP MediaRenderer service active at http://%s:%d/ ✓", self.host, self.port)

    async def stop(self) -> None:
        if self._site:
            await self._site.stop()
            self._site = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        self._devices.clear()
        logger.info("Virtual UPnP MediaRenderer service stopped.")

    # ------------------------------------------------------------------
    # HTTP Route Handlers
    # ------------------------------------------------------------------

    async def _handle_description(self, request: web.Request) -> web.Response:
        device_key = request.match_info["device_key"]
        dev = self._devices.get(device_key)
        if not dev:
            return web.Response(status=404, text="Device Not Found")

        base_url = f"http://{self.host}:{self.port}/{device_key}"
        xml_body = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<root xmlns="urn:schemas-upnp-org:device-1-0">\n'
            "  <specVersion><major>1</major><minor>0</minor></specVersion>\n"
            "  <device>\n"
            "    <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>\n"
            f"    <friendlyName>{dev.friendly_name}</friendlyName>\n"
            "    <manufacturer>JCastBridge</manufacturer>\n"
            "    <manufacturerURL>https://github.com/danceden99-ops/jellyfin-jcast-bridge</manufacturerURL>\n"
            "    <modelDescription>Virtual UPnP MediaRenderer for Google Cast</modelDescription>\n"
            "    <modelName>Chromecast Virtual Renderer</modelName>\n"
            "    <modelNumber>1.0</modelNumber>\n"
            f"    <UDN>{dev.udn}</UDN>\n"
            "    <serviceList>\n"
            "      <service>\n"
            "        <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>\n"
            "        <serviceId>urn:upnp-org:serviceId:AVTransport</serviceId>\n"
            f"        <controlURL>{base_url}/AVTransport/control</controlURL>\n"
            "        <eventSubURL></eventSubURL>\n"
            f"        <SCPDURL>{base_url}/AVTransport/scpd.xml</SCPDURL>\n"
            "      </service>\n"
            "      <service>\n"
            "        <serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>\n"
            "        <serviceId>urn:upnp-org:serviceId:RenderingControl</serviceId>\n"
            f"        <controlURL>{base_url}/RenderingControl/control</controlURL>\n"
            "        <eventSubURL></eventSubURL>\n"
            f"        <SCPDURL>{base_url}/RenderingControl/scpd.xml</SCPDURL>\n"
            "      </service>\n"
            "      <service>\n"
            "        <serviceType>urn:schemas-upnp-org:service:ConnectionManager:1</serviceType>\n"
            "        <serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>\n"
            f"        <controlURL>{base_url}/ConnectionManager/control</controlURL>\n"
            "        <eventSubURL></eventSubURL>\n"
            f"        <SCPDURL>{base_url}/ConnectionManager/scpd.xml</SCPDURL>\n"
            "      </service>\n"
            "    </serviceList>\n"
            "  </device>\n"
            "</root>"
        )
        return web.Response(text=xml_body, content_type="text/xml; charset=utf-8")

    async def _handle_scpd(self, request: web.Request) -> web.Response:
        service = request.match_info["service"]
        if service == "AVTransport":
            xml_body = (
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<scpd xmlns="urn:schemas-upnp-org:service-1-0">\n'
                "  <specVersion><major>1</major><minor>0</minor></specVersion>\n"
                "  <actionList>\n"
                "    <action><name>SetAVTransportURI</name></action>\n"
                "    <action><name>Play</name></action>\n"
                "    <action><name>Pause</name></action>\n"
                "    <action><name>Stop</name></action>\n"
                "    <action><name>Seek</name></action>\n"
                "    <action><name>GetPositionInfo</name></action>\n"
                "    <action><name>GetTransportInfo</name></action>\n"
                "    <action><name>GetMediaInfo</name></action>\n"
                "    <action><name>GetDeviceCapabilities</name></action>\n"
                "    <action><name>GetTransportSettings</name></action>\n"
                "  </actionList>\n"
                "</scpd>"
            )
        elif service == "RenderingControl":
            xml_body = (
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<scpd xmlns="urn:schemas-upnp-org:service-1-0">\n'
                "  <specVersion><major>1</major><minor>0</minor></specVersion>\n"
                "  <actionList>\n"
                "    <action><name>SetVolume</name></action>\n"
                "    <action><name>GetVolume</name></action>\n"
                "    <action><name>SetMute</name></action>\n"
                "    <action><name>GetMute</name></action>\n"
                "  </actionList>\n"
                "</scpd>"
            )
        else:  # ConnectionManager
            xml_body = (
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<scpd xmlns="urn:schemas-upnp-org:service-1-0">\n'
                "  <specVersion><major>1</major><minor>0</minor></specVersion>\n"
                "  <actionList>\n"
                "    <action><name>GetProtocolInfo</name></action>\n"
                "    <action><name>GetCurrentConnectionIDs</name></action>\n"
                "  </actionList>\n"
                "</scpd>"
            )
        return web.Response(text=xml_body, content_type="text/xml; charset=utf-8")

    async def _handle_control(self, request: web.Request) -> web.Response:
        device_key = request.match_info["device_key"]
        service = request.match_info["service"]
        dev = self._devices.get(device_key)
        if not dev:
            return web.Response(status=404, text="Device Not Found")

        soap_action_header = request.headers.get("SOAPAction", "").strip('"')
        action_name = soap_action_header.split("#")[-1] if "#" in soap_action_header else ""

        body_bytes = await request.read()
        root = None
        if body_bytes:
            try:
                root = ET.fromstring(body_bytes)
            except Exception:
                pass

        if service == "AVTransport":
            return await self._dispatch_avtransport(dev, action_name, root)
        elif service == "RenderingControl":
            return await self._dispatch_rendering_control(dev, action_name, root)
        elif service == "ConnectionManager":
            return self._dispatch_connection_manager(action_name)

        return web.Response(status=400, text="Unknown Service")

    # ------------------------------------------------------------------
    # AVTransport Actions
    # ------------------------------------------------------------------

    async def _dispatch_avtransport(
        self, dev: VirtualRendererDevice, action: str, root: Optional[ET.Element]
    ) -> web.Response:
        client = dev.cast_client

        if action == "SetAVTransportURI":
            current_uri = ""
            metadata = ""
            if root is not None:
                for elem in root.iter():
                    if elem.tag.endswith("CurrentURI"):
                        current_uri = elem.text or ""
                    elif elem.tag.endswith("CurrentURIMetaData"):
                        metadata = elem.text or ""

            dev.current_uri = current_uri
            dev.current_metadata = metadata

            # Extract basic title/artist from DIDL metadata if present
            title = ""
            artist = ""
            album = ""
            if metadata:
                try:
                    didl = ET.fromstring(metadata)
                    for item in didl.iter():
                        tag_lower = item.tag.lower()
                        if "title" in tag_lower and not title:
                            title = item.text or ""
                        elif ("creator" in tag_lower or "artist" in tag_lower) and not artist:
                            artist = item.text or ""
                        elif "album" in tag_lower and not album:
                            album = item.text or ""
                except Exception:
                    pass

            dev.title = title
            dev.artist = artist
            dev.album = album

            # Deduce audio content type
            content_type = "audio/flac"
            if ".mp3" in current_uri.lower():
                content_type = "audio/mpeg"
            elif ".m4a" in current_uri.lower() or ".aac" in current_uri.lower():
                content_type = "audio/mp4"
            elif ".wav" in current_uri.lower():
                content_type = "audio/wav"
            elif ".mkv" in current_uri.lower() or ".mp4" in current_uri.lower():
                content_type = "video/mp4"

            logger.info("JRiver requested SetAVTransportURI on '%s': %s", dev.friendly_name, current_uri[:100])
            await client.load_media(
                content_id=current_uri,
                content_type=content_type,
                title=title,
                artist=artist,
                album=album,
                autoplay=True,
            )
            return web.Response(
                text=_build_soap_response("SetAVTransportURI", "AVTransport", ""),
                content_type="text/xml; charset=utf-8",
            )

        elif action == "Play":
            logger.info("JRiver requested Play on '%s'", dev.friendly_name)
            await client.play()
            return web.Response(
                text=_build_soap_response("Play", "AVTransport", ""),
                content_type="text/xml; charset=utf-8",
            )

        elif action == "Pause":
            logger.info("JRiver requested Pause on '%s'", dev.friendly_name)
            await client.pause()
            return web.Response(
                text=_build_soap_response("Pause", "AVTransport", ""),
                content_type="text/xml; charset=utf-8",
            )

        elif action == "Stop":
            logger.info("JRiver requested Stop on '%s'", dev.friendly_name)
            await client.stop()
            return web.Response(
                text=_build_soap_response("Stop", "AVTransport", ""),
                content_type="text/xml; charset=utf-8",
            )

        elif action == "Seek":
            target = "00:00:00"
            if root is not None:
                for elem in root.iter():
                    if elem.tag.endswith("Target"):
                        target = elem.text or "00:00:00"
            target_secs = _time_str_to_seconds(target)
            logger.info("JRiver requested Seek to %s (%.1fs) on '%s'", target, target_secs, dev.friendly_name)
            await client.seek(target_secs)
            return web.Response(
                text=_build_soap_response("Seek", "AVTransport", ""),
                content_type="text/xml; charset=utf-8",
            )

        elif action == "GetTransportInfo":
            state = client.player_state
            resp = (
                f"<CurrentTransportState>{state}</CurrentTransportState>"
                "<CurrentTransportStatus>OK</CurrentTransportStatus>"
                "<CurrentSpeed>1</CurrentSpeed>"
            )
            return web.Response(
                text=_build_soap_response("GetTransportInfo", "AVTransport", resp),
                content_type="text/xml; charset=utf-8",
            )

        elif action == "GetPositionInfo":
            dur_str = _seconds_to_time_str(client.duration)
            rel_str = _seconds_to_time_str(client.current_time)
            resp = (
                "<Track>1</Track>"
                f"<TrackDuration>{dur_str}</TrackDuration>"
                f"<TrackMetaData>{dev.current_metadata}</TrackMetaData>"
                f"<TrackURI>{dev.current_uri}</TrackURI>"
                f"<RelTime>{rel_str}</RelTime>"
                f"<AbsTime>{rel_str}</AbsTime>"
                "<RelCount>0</RelCount>"
                "<AbsCount>0</AbsCount>"
            )
            return web.Response(
                text=_build_soap_response("GetPositionInfo", "AVTransport", resp),
                content_type="text/xml; charset=utf-8",
            )

        elif action == "GetMediaInfo":
            dur_str = _seconds_to_time_str(client.duration)
            resp = (
                "<NrTracks>1</NrTracks>"
                f"<MediaDuration>{dur_str}</MediaDuration>"
                f"<CurrentURI>{dev.current_uri}</CurrentURI>"
                f"<CurrentURIMetaData>{dev.current_metadata}</CurrentURIMetaData>"
                "<NextURI></NextURI>"
                "<NextURIMetaData></NextURIMetaData>"
                "<PlayMedium>NETWORK</PlayMedium>"
                "<RecordMedium>NOT_IMPLEMENTED</RecordMedium>"
                "<WriteStatus>NOT_IMPLEMENTED</WriteStatus>"
            )
            return web.Response(
                text=_build_soap_response("GetMediaInfo", "AVTransport", resp),
                content_type="text/xml; charset=utf-8",
            )

        elif action == "GetDeviceCapabilities":
            resp = (
                "<PlayMedia>NETWORK,NONE</PlayMedia>"
                "<RecMedia>NOT_IMPLEMENTED</RecMedia>"
                "<RecQualityModes>NOT_IMPLEMENTED</RecQualityModes>"
            )
            return web.Response(
                text=_build_soap_response("GetDeviceCapabilities", "AVTransport", resp),
                content_type="text/xml; charset=utf-8",
            )

        elif action == "GetTransportSettings":
            resp = "<PlayMode>NORMAL</PlayMode><RecQualityMode>NOT_IMPLEMENTED</RecQualityMode>"
            return web.Response(
                text=_build_soap_response("GetTransportSettings", "AVTransport", resp),
                content_type="text/xml; charset=utf-8",
            )

        # Fallback empty response
        return web.Response(
            text=_build_soap_response(action, "AVTransport", ""),
            content_type="text/xml; charset=utf-8",
        )

    # ------------------------------------------------------------------
    # RenderingControl Actions
    # ------------------------------------------------------------------

    async def _dispatch_rendering_control(
        self, dev: VirtualRendererDevice, action: str, root: Optional[ET.Element]
    ) -> web.Response:
        client = dev.cast_client

        if action == "SetVolume":
            vol = 50
            if root is not None:
                for elem in root.iter():
                    if elem.tag.endswith("DesiredVolume"):
                        try:
                            vol = int(elem.text or 50)
                        except Exception:
                            pass
            level = max(0.0, min(1.0, vol / 100.0))
            logger.info("JRiver requested SetVolume on '%s': %d%% (level=%.2f)", dev.friendly_name, vol, level)
            await client.set_volume(level)
            return web.Response(
                text=_build_soap_response("SetVolume", "RenderingControl", ""),
                content_type="text/xml; charset=utf-8",
            )

        elif action == "GetVolume":
            current_vol = int(round(client.volume_level * 100))
            resp = f"<CurrentVolume>{current_vol}</CurrentVolume>"
            return web.Response(
                text=_build_soap_response("GetVolume", "RenderingControl", resp),
                content_type="text/xml; charset=utf-8",
            )

        elif action == "SetMute":
            mute = False
            if root is not None:
                for elem in root.iter():
                    if elem.tag.endswith("DesiredMute"):
                        text_val = (elem.text or "").strip().lower()
                        mute = text_val in ("1", "true")
            logger.info("JRiver requested SetMute on '%s': %s", dev.friendly_name, mute)
            await client.set_muted(mute)
            return web.Response(
                text=_build_soap_response("SetMute", "RenderingControl", ""),
                content_type="text/xml; charset=utf-8",
            )

        elif action == "GetMute":
            current_mute = 1 if client.is_muted else 0
            resp = f"<CurrentMute>{current_mute}</CurrentMute>"
            return web.Response(
                text=_build_soap_response("GetMute", "RenderingControl", resp),
                content_type="text/xml; charset=utf-8",
            )

        return web.Response(
            text=_build_soap_response(action, "RenderingControl", ""),
            content_type="text/xml; charset=utf-8",
        )

    def _dispatch_connection_manager(self, action: str) -> web.Response:
        if action == "GetProtocolInfo":
            resp = (
                "<Source></Source>"
                "<Sink>http-get:*:audio/flac:*,http-get:*:audio/mp3:*,http-get:*:audio/mpeg:*,http-get:*:audio/mp4:*,http-get:*:audio/wav:*,http-get:*:audio/x-wav:*,http-get:*:video/mp4:*</Sink>"
            )
            return web.Response(
                text=_build_soap_response("GetProtocolInfo", "ConnectionManager", resp),
                content_type="text/xml; charset=utf-8",
            )
        elif action == "GetCurrentConnectionIDs":
            resp = "<ConnectionIDs>0</ConnectionIDs>"
            return web.Response(
                text=_build_soap_response("GetCurrentConnectionIDs", "ConnectionManager", resp),
                content_type="text/xml; charset=utf-8",
            )

        return web.Response(
            text=_build_soap_response(action, "ConnectionManager", ""),
            content_type="text/xml; charset=utf-8",
        )
