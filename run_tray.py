#!/usr/bin/env python3
"""
Windows System Tray Application for Jellyfin → JRiver Bridge.

Features:
- Runs quietly in the Windows system notification area (system tray).
- Dynamic color-coded tray icon:
    * GREEN  : Connected and healthy (both JRiver and Jellyfin reachable).
    * RED    : Connection error or offline service.
    * AMBER  : Connecting / initializing.
    * GRAY   : Disabled / stopped.
- Tray context menu:
    * Live Status header (JRiver & Jellyfin health).
    * [✓] Enabled toggle (starts/stops bridge service without exiting).
    * [✓] Enable File Logging toggle (turns on/off writing to bridge.log).
    * Open Configuration Directory (launches Windows Explorer).
    * Edit config.yaml in default text editor.
    * View Live Log file.
    * Check Connection Now.
    * Exit (clean shutdown).
- Rolling Log File:
    * Automatically written to the directory containing config.yaml.
    * Capped at 2,000 lines (when exceeded, overwrites with a fresh log).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from typing import Optional

# Suppress noisy unraisable transport teardown warnings during interpreter shutdown
sys.unraisablehook = lambda unraisable: None

# In PyInstaller frozen bundle on Windows, ensure _MEIPASS and subdirectories are in DLL search path
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    for dll_dir in [
        sys._MEIPASS,
        os.path.join(sys._MEIPASS, "cryptography", "hazmat", "bindings"),
    ]:
        if os.path.isdir(dll_dir):
            try:
                os.add_dll_directory(dll_dir)
            except Exception:
                pass

from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item
import yaml

# Ensure project root / executable directory is in sys.path
if getattr(sys, "frozen", False):
    # Running as a compiled PyInstaller executable: use the folder containing the .exe
    PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    # Running from Python source script: use the script directory
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from jellyfin_jriver_bridge.service import BridgeService


class LineCappedFileHandler(logging.Handler):
    """
    A logging handler that writes to a file and resets/overwrites
    when reaching a maximum line limit (default: 2,000 lines).
    """

    def __init__(self, filename: str, max_lines: int = 2000, encoding: str = "utf-8"):
        super().__init__()
        self.filename = filename
        self.max_lines = max_lines
        self.encoding = encoding
        self._line_count = self._count_lines()
        self._file = open(self.filename, "a", encoding=self.encoding, errors="replace")

    def _count_lines(self) -> int:
        if not os.path.isfile(self.filename):
            return 0
        try:
            with open(self.filename, "r", encoding=self.encoding, errors="replace") as f:
                return sum(1 for _ in f)
        except Exception:
            return 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record) + "\n"
            if self._line_count >= self.max_lines:
                # Re-open in write mode to overwrite with fresh log
                self._file.close()
                self._file = open(self.filename, "w", encoding=self.encoding, errors="replace")
                self._file.write(f"--- Log rotated at {time.strftime('%Y-%m-%d %H:%M:%S')} (capped at {self.max_lines} lines) ---\n")
                self._line_count = 1

            self._file.write(msg)
            self._file.flush()
            self._line_count += 1
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        if self._file and not self._file.closed:
            self._file.flush()
            self._file.close()
        super().close()


def create_tray_icon_image(color: str) -> Image.Image:
    """Generate a clean high-DPI 64x64 circle icon for the system tray."""
    size = (64, 64)
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    color_map = {
        "green": ("#10B981", "#059669"),   # Emerald green
        "red": ("#EF4444", "#DC2626"),     # Vivid red
        "amber": ("#F59E0B", "#D97706"),   # Warm amber/yellow
        "gray": ("#6B7280", "#4B5563"),    # Slate gray
    }
    fill_color, border_color = color_map.get(color, color_map["gray"])

    # Outer border / subtle ring
    draw.ellipse((4, 4, 60, 60), fill=border_color)
    # Core circle
    draw.ellipse((7, 7, 57, 57), fill=fill_color)
    # Highlight reflection for subtle 3D depth
    draw.ellipse((14, 12, 30, 24), fill=(255, 255, 255, 90))

    return image


class TrayApp:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = (
            config_path
            if os.path.isabs(config_path)
            else os.path.join(PROJECT_ROOT, config_path)
        )
        self.config_dir = os.path.dirname(os.path.abspath(self.config_path))
        self.log_file = os.path.join(self.config_dir, "bridge.log")

        # Setup Logging
        self.log_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.console_handler = logging.StreamHandler(sys.stdout)
        self.console_handler.setFormatter(self.log_formatter)

        self.file_handler: Optional[LineCappedFileHandler] = None
        self.logging_enabled = True

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(self.console_handler)

        self._init_file_logging(enable=True)
        self.logger = logging.getLogger("bridge-tray")

        # Config & Service
        self.config = self._load_config()
        self.service = BridgeService(self.config, self.config_dir)

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None

        self.status_text = "Initializing …"
        self.current_color = "amber"
        self.icon: Optional[pystray.Icon] = None

        # Link service status updates directly to tray icon updates
        self.service.on_status_change = self._on_service_status_change

    def _init_file_logging(self, enable: bool) -> None:
        root_logger = logging.getLogger()
        if enable:
            if not self.file_handler:
                try:
                    self.file_handler = LineCappedFileHandler(self.log_file, max_lines=2000)
                    self.file_handler.setFormatter(self.log_formatter)
                    root_logger.addHandler(self.file_handler)
                    self.logging_enabled = True
                except Exception as e:
                    print(f"Failed to enable file logging: {e}", file=sys.stderr)
        else:
            if self.file_handler:
                root_logger.removeHandler(self.file_handler)
                self.file_handler.close()
                self.file_handler = None
            self.logging_enabled = False

    def _load_config(self) -> dict:
        if not os.path.isfile(self.config_path):
            self._write_default_config()
        if os.path.isfile(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _write_default_config(self) -> None:
        default_yaml = (
            "# Jellyfin Cast -> JRiver Media Center Bridge Configuration\n"
            "jriver:\n"
            "  host: \"localhost\"\n"
            "  port: 52199\n"
            "  username: null\n"
            "  password: null\n"
            "  zone: null\n"
            "  use_ssl: false\n\n"
            "cast:\n"
            "  device_name: \"JRiver Media Center\"\n"
            "  port: 8009\n"
            "  eureka_port: 8008\n\n"
            "jellyfin:\n"
            "  url: \"http://localhost:8096\"\n"
            "  username: \"your_jellyfin_username\"\n"
            "  password: \"your_jellyfin_password\"\n"
            "  device_name: \"JRiver Media Center\"\n\n"
            "log_level: \"INFO\"\n"
        )
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                f.write(default_yaml)
        except Exception:
            pass

    def _on_service_status_change(self, mcws_ok: bool, jellyfin_ok: bool, message: str) -> None:
        self.status_text = message
        if not self.service.is_running:
            self._update_icon("gray", "JRiver Bridge: Disabled")
        elif mcws_ok and jellyfin_ok:
            self._update_icon("green", f"JRiver Bridge: Healthy ({message})")
        else:
            self._update_icon("red", f"JRiver Bridge: Degraded ({message})")

    def _update_icon(self, color: str, title: str) -> None:
        self.current_color = color
        if self.icon:
            self.icon.icon = create_tray_icon_image(color)
            self.icon.title = title[:127]  # Windows tray tooltip limit is 128 chars

    # ------------------------------------------------------------------
    # Background Asyncio Runner
    # ------------------------------------------------------------------

    def _run_event_loop(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # Silence Proactor transport teardown warnings on Windows shutdown
        def _silent_exception_handler(loop, context):
            pass

        self.loop.set_exception_handler(_silent_exception_handler)

        try:
            self.loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            except Exception:
                pass
            try:
                self.loop.close()
            except Exception:
                pass

    def _safe_start_service(self) -> None:
        if not self.loop:
            return

        async def _run():
            try:
                await self.service.start()
            except Exception as e:
                self.logger.error("Bridge service startup failed: %s", e, exc_info=True)
                self._on_service_status_change(False, False, f"Startup error: {e}")

        asyncio.run_coroutine_threadsafe(_run(), self.loop)

    def start_background_service(self) -> None:
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()

        while not self.loop or not self.loop.is_running():
            time.sleep(0.05)
        self._safe_start_service()

    # ------------------------------------------------------------------
    # Menu Actions
    # ------------------------------------------------------------------

    def toggle_enable(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if not self.loop:
            return

        if self.service.is_running:
            self.logger.info("User requested Disable from Tray Menu")
            asyncio.run_coroutine_threadsafe(self.service.stop(), self.loop)
            self._update_icon("gray", "JRiver Bridge: Disabled")
        else:
            self.logger.info("User requested Enable from Tray Menu")
            self._update_icon("amber", "JRiver Bridge: Connecting …")
            self._safe_start_service()

    def is_enabled(self, item: pystray.MenuItem) -> bool:
        return self.service.is_running

    def toggle_logging(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        new_state = not self.logging_enabled
        self._init_file_logging(enable=new_state)
        self.logger.info("File logging %s by user", "enabled" if new_state else "disabled")

    def is_logging_enabled(self, item: pystray.MenuItem) -> bool:
        return self.logging_enabled

    def check_now(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if self.loop and self.service.is_running:
            self.logger.info("Triggering manual health check from Tray Menu")
            async def _check():
                jr, jf = await self.service.check_health()
                msg = f"JRiver: {'OK' if jr else 'Offline'} | Jellyfin: {'OK' if jf else 'Offline'}"
                self._on_service_status_change(jr, jf, msg)
            asyncio.run_coroutine_threadsafe(_check(), self.loop)

    def open_config_directory(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self.logger.info("Opening config directory: %s", self.config_dir)
        try:
            os.startfile(self.config_dir)
        except Exception as e:
            self.logger.error("Failed to open config directory: %s", e)

    def open_config_file(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self.logger.info("Opening config file: %s", self.config_path)
        try:
            os.startfile(self.config_path)
        except Exception as e:
            self.logger.error("Failed to open config file: %s", e)

    def view_logs(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self.logger.info("Opening log file: %s", self.log_file)
        try:
            if not os.path.exists(self.log_file):
                with open(self.log_file, "w", encoding="utf-8") as f:
                    f.write("--- JRiver Bridge Log Started ---\n")
            os.startfile(self.log_file)
        except Exception as e:
            self.logger.error("Failed to open log file: %s", e)

    def exit_app(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self.logger.info("Exiting application from System Tray …")
        if self.loop and self.loop.is_running():
            try:
                if self.service.is_running:
                    fut = asyncio.run_coroutine_threadsafe(self.service.stop(), self.loop)
                    fut.result(timeout=4)
            except Exception as e:
                self.logger.debug("Shutdown wait error: %s", e)
            finally:
                self.loop.call_soon_threadsafe(self.loop.stop)
                if self.thread and self.thread.is_alive():
                    self.thread.join(timeout=3.0)
        self._init_file_logging(enable=False)
        icon.stop()

    # ------------------------------------------------------------------
    # Tray Menu Construction & Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.start_background_service()

        menu = pystray.Menu(
            item(lambda text: f"Status: {self.status_text}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            item("Enabled", self.toggle_enable, checked=self.is_enabled),
            item("Enable File Logging", self.toggle_logging, checked=self.is_logging_enabled),
            pystray.Menu.SEPARATOR,
            item("Open Configuration Directory", self.open_config_directory),
            item("Edit config.yaml", self.open_config_file),
            item("View Live Logs", self.view_logs),
            item("Check Connection Now", self.check_now),
            pystray.Menu.SEPARATOR,
            item("Exit", self.exit_app),
        )

        self.icon = pystray.Icon(
            name="JRiverBridge",
            icon=create_tray_icon_image("amber"),
            title="JRiver Cast Bridge: Initializing …",
            menu=menu,
        )

        self.logger.info("JRiver Bridge Windows System Tray icon active ✓")
        self.icon.run()


if __name__ == "__main__":
    app = TrayApp()
    app.run()
