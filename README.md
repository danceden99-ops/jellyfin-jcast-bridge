# Jellyfin Cast → JRiver Media Center Bridge

A high-performance Windows system tray service and Cast bridge that makes **JRiver Media Center** appear as an active remote playback target and Cast receiver for **Jellyfin**. 

Cast video and audio from any Jellyfin client (Web, Desktop, iOS, Android, Smart TV) directly to JRiver Media Center with full remote control (Play, Pause, Seek, Volume, Stop), zone pinning, automatic fullscreen display exit, and timeline synchronization.

Available both as a **standalone, zero-dependency Windows executable (`.exe`)** and as a **Python service**.

---

## Architecture Overview

```
                      ┌────────────────────────────────────────────────┐
                      │              Jellyfin Ecosystem                │
                      │  (Web Client, Mobile Apps, TV, Desktop Client) │
                      └───────┬────────────────────────────────┬───────┘
                              │                                │
                 Direct Jellyfin WebSocket               Google Cast V2
                 Remote Control Protocol                 (TLS / Port 8009)
                              │                                │
                              ▼                                ▼
       ┌────────────────────────────────────────────────────────────────────────┐
       │                 Jellyfin → JRiver Bridge Application                   │
       │                                                                        │
       │  ┌─────────────────────────┐            ┌───────────────────────────┐  │
       │  │ Jellyfin Remote Client  │            │ Cast V2 Protocol Receiver │  │
       │  │ • Persistent Device ID  │            │ • Eureka HTTP (Port 8008) │  │
       │  │ • User / Token Auth     │            │ • TLS Server (Port 8009)  │  │
       │  │ • Session Capabilities  │            │ • AsyncZeroconf mDNS      │  │
       │  │ • Bidirectional Keep-   │            │ • Device Auth Handshake   │  │
       │  │   Alive & Heartbeats    │            │ • Protocol Buffer Framing │  │
       │  │ • Real-time Progress    │            │ • Clean Connection Drain  │  │
       │  └───────────┬─────────────┘            └─────────────┬─────────────┘  │
       │              │                                        │                │
       │              └───────────────────┬────────────────────┘                │
       │                                  ▼                                     │
       │                      ┌───────────────────────┐                         │
       │                      │   Bridge Controller   │                         │
       │                      │ • Metadata Inspection │                         │
       │                      │ • URL Stream Routing  │                         │
       │                      │ • Play/Pause Toggle   │                         │
       │                      │ • Auto-Stop on Switch │                         │
       │                      └───────────┬───────────┘                         │
       │                                  │                                     │
       │                                  ▼                                     │
       │                      ┌───────────────────────┐                         │
       │                      │   JRiver MCWS Client  │                         │
       │                      │ • Alive Health Checks │                         │
       │                      │ • Concrete Zone ID    │                         │
       │                      │   Pinning (Zone ID=0) │                         │
       │                      │ • Bounded Buffer Wait │                         │
       │                      │ • Escape on Stop (GUI)│                         │
       │                      └───────────┬───────────┘                         │
       └──────────────────────────────────┼─────────────────────────────────────┘
                                          │ MCWS REST (Port 52199, Zone=ID)
                                          ▼
                      ┌───────────────────────────────────────┐
                      │          JRiver Media Center          │
                      │ • High-performance DirectShow/LAV    │
                      │ • Custom GLSL & madVR video rendering │
                      │ • Bit-perfect audio output            │
                      └───────────────────────────────────────┘
```

### Core Architecture & Key Features
1. **Direct Jellyfin Remote Player Session**:
   - Authenticates directly against your Jellyfin Server API (`/Users/AuthenticateByName` or API key).
   - Registers JRiver as an active remote player using a permanent device identifier (`/Sessions/Capabilities/Full`).
   - Maintains a persistent WebSocket (`/socket`) with bidirectional keep-alives and ping-pong loop prevention to ensure the remote player bar never detaches.
   - Reports live playback state (`/Sessions/Playing/Progress`) with `CanSeek: True` and `PlayMethod: DirectStream`.
   - **Accurate Idle / Stop Detection**: Distinguishes between initial stream buffering and genuine playback stop. Releasing the Jellyfin session (`/Sessions/Playing/Stopped`) when JRiver stops allows back-to-back video casting without session locks.
   - **Auto Clean-Up on Media Switch**: When a new video is cast while an older title is active, the bridge immediately closes the prior session cleanly before starting the new stream.
2. **JRiver MCWS Integration & Zone Pinning**:
   - **Concrete Zone ID Pinning**: Captures the concrete `ZoneID` (e.g. `ZoneID=0` "Player") upon playback start and pins all subsequent commands (`Pause`, `Play`, `Seek`, `Stop`) directly to that zone, preventing loss of control if GUI window focus shifts.
   - **Automatic Fullscreen Display Exit**: On stop, issues an `Escape` key command via MCWS to cleanly exit JRiver's fullscreen "Display View" back to the standard or Theater View GUI.
   - Direct stream URL formulation with container extensions (`stream.{container}?static=true`) or local/UNC paths (`\\server\share\...`) for optimal DirectShow/LAV splitters.
3. **Google Cast V2 Protocol Receiver**:
   - Advertises via mDNS Zeroconf (`_googlecast._tcp`).
   - Serves Cast V2 protocol buffers over TLS on port 8009 and Eureka device metadata on port 8008.
   - Emulates Chromecast device handshakes for browser and mobile Cast senders.

---

## Windows System Tray Application

The bridge includes a native Windows notification area (System Tray) runner (`run_tray.py` / `JRiverCastBridge.exe`):

```
┌────────────────────────────────────────────────────────┐
│ Windows System Tray (Taskbar Notification Area)        │
│                                                        │
│  [ (●) Green / (●) Red / (●) Amber / (●) Gray Icon ]   │
│      │                                                 │
│      ├─ Status: JRiver: OK | Jellyfin: OK              │
│      ├─ [✓] Enabled                                    │
│      ├─ [✓] Enable File Logging                        │
│      ├─ Open Configuration Directory                   │
│      ├─ Edit config.yaml                               │
│      ├─ View Live Logs                                 │
│      ├─ Check Connection Now                           │
│      └─ Exit                                           │
└────────────────────────────────────────────────────────┘
```

- **Dynamic Color Indicators**:
  - 🟢 **Green**: Both JRiver MCWS and Jellyfin Server are reachable and healthy.
  - 🔴 **Red**: Connection error (either JRiver is offline or Jellyfin is unreachable).
  - 🟡 **Amber**: Starting up / connecting.
  - ⚪ **Gray**: Disabled / paused.
- **Context Menu Controls**:
  - **Status Header**: Real-time health summary of both endpoints.
  - **Enabled [✓]**: Toggle the bridge on/off without closing the tray application.
  - **Enable File Logging [✓]**: Toggle live file logging to `bridge.log` without restarting.
  - **Open Configuration Directory**: Launches Windows Explorer directly to the folder containing `config.yaml`.
  - **Edit config.yaml**: Opens your settings file in your default text editor.
  - **View Live Logs**: Opens `bridge.log` for immediate inspection.
  - **Check Connection Now**: Triggers an immediate health check.
  - **Exit**: Cleanly drains network transports, joins event loop threads, and exits with zero console error tracebacks.
- **2,000-Line Rolling Log Cap**:
  - `bridge.log` is capped at 2,000 lines. When reached, it rotates with a clean header to prevent disk bloat.

---

## Standalone Executable (`.exe`) Build & Deployment

You can compile the entire application into a single, standalone executable that requires **no Python installation**, no `.venv`, and no environment variables on target machines.

### 1. Compile the Executable
> **Important**: If `JRiverCastBridge.exe` is currently running, right-click its System Tray icon and select **Exit** first so Windows does not lock the binary during compilation.

In the project directory, double-click or run:
```cmd
build_exe.bat
```
This script will:
- Check for PyInstaller (auto-installing via `pip` if needed).
- Compile `run_tray.py` using `JRiverCastBridge.spec` with full C-extension bundling (`cryptography`, `pystray`, `zeroconf`, `aiohttp`) into a single windowless binary.
- Automatically clean previous builds (`--clean --noconfirm`).
- Output the executable to `dist\JRiverCastBridge.exe`, copy `config.yaml`, and stage the TLS certificates in `dist\certs\`.

### 2. Standalone Deployment
Copy the compiled `dist\` folder to any location on your Media Player PC (e.g. `C:\Tools\JRiverCastBridge\` or `D:\Apps\JRiverCastBridge\`):
```
C:\Tools\JRiverCastBridge\
├── JRiverCastBridge.exe     (Standalone ~24MB windowless binary)
├── config.yaml              (Application configuration)
└── certs/                   (TLS certificates for Cast V2)
    ├── cast_bridge.crt
    └── cast_bridge.key
```

- **Freeze-Aware Paths**: When running as an `.exe`, all paths (`config.yaml`, `bridge.log`, and `certs/`) resolve automatically to the directory where `JRiverCastBridge.exe` is located.
- **Embedded Cryptography Engine**: The executable includes compiled native cryptography support. If the `certs/` folder is ever removed, `JRiverCastBridge.exe` will generate fresh 10-year self-signed certificates on-the-fly without needing external OpenSSL binaries.
- **Auto-Config Generation**: If `JRiverCastBridge.exe` is run in an empty folder without `config.yaml`, it automatically creates a fully commented starter `config.yaml` template.
- **Auto-Start with Windows**: Create a shortcut to `JRiverCastBridge.exe`, press `Win + R`, type `shell:startup`, and paste the shortcut into your Windows Startup folder.

---

## Python Installation & Setup (Alternative to `.exe`)

If running from source rather than the standalone executable:

### 1. Requirements
- **Windows 10 / 11**
- **Python 3.10+** (Python 3.12, 3.13, or 3.15)
- **JRiver Media Center** (v28+) with Media Network / MCWS enabled
- **Jellyfin Server** (v10.8+ or v12.x) on the local network

### 2. Install Dependencies
Open Command Prompt or PowerShell in the project directory:
```cmd
pip install -r requirements.txt
```

### 3. Enable MCWS in JRiver Media Center
1. In JRiver Media Center, open **Tools → Options → Media Network**.
2. Check **Use Media Network to share this library and enable DLNA**.
3. Note your **MCWS port** (default: `52199`).
4. If authentication is enabled, note your username and password.

---

## Configuration (`config.yaml`)

Edit `config.yaml` to match your local network IP addresses:

```yaml
# ─── JRiver Media Center settings ────────────────────────────────────────────
jriver:
  host: "192.168.xxx.xxx"      # IP address of the machine running JRiver MC (e.g. 192.168.1.100)
  port: 52199                  # MCWS port (default 52199, HTTPS default 52200)
  username: null               # MCWS username (null = no authentication)
  password: null               # MCWS password
  zone: null                   # Zone name or null for active zone targeting
  use_ssl: false               # true to use HTTPS for MCWS

# ─── Cast receiver settings ──────────────────────────────────────────────────
cast:
  device_name: "JRiver Media Center"   # Name shown in Cast / Play On menus
  port: 8009                           # Cast protocol port (standard 8009)
  eureka_port: 8008                    # Eureka device info HTTP port
  cert_file: "certs/cast_bridge.crt"   # TLS certificate (auto-generated)
  key_file: "certs/cast_bridge.key"    # TLS private key  (auto-generated)
  device_id: null                      # Unique device ID (auto-generated if null)
  bind_address: null                   # IP to bind to (null = auto-detect LAN IP)
  status_interval: 1.0                 # Seconds between status updates

# ─── Jellyfin Server settings ────────────────────────────────────────────────
jellyfin:
  url: "http://192.168.xxx.xxx:8096"   # URL of your Jellyfin server (e.g. http://192.168.1.50:8096)
  username: "your_jellyfin_username"   # Jellyfin username
  password: "your_jellyfin_password"   # Jellyfin password
  api_key: null                        # Optional: API key from Dashboard -> API Keys
  device_name: "JRiver Media Center"

# ─── URL rewrite rules ───────────────────────────────────────────────────────
# Optional find->replace rules for media URLs if needed across network subnets:
url_rewrite:
  # "http://localhost:8096": "http://192.168.xxx.xxx:8096"

# ─── Logging ─────────────────────────────────────────────────────────────────
log_level: "INFO"   # DEBUG for detailed protocol trace, INFO for normal operation
```

---

## How to Run

### Option A: Standalone Executable (Recommended)
Double-click `JRiverCastBridge.exe`. It runs silently in your Windows System Tray.

### Option B: Python Launchers
- **Silent Background Launch**:
  - Double-click **`start_tray_silent.vbs`** or **`start_tray_silent.bat`**.
  - Windowless execution; sits directly in the Windows system notification area.
- **Visible Diagnostic Console Launch**:
  - Double-click **`start_tray.bat`** (or run `python run_tray.py`).
  - Opens a visible console displaying live startup logs and pauses on error for easy debugging.

### Option C: CLI Mode
For console-only or headless servers:
```powershell
python run.py
```
For verbose protocol debugging:
```powershell
python run.py -v
```

---

## How to Cast from Jellyfin

1. Open Jellyfin in your browser, phone, tablet, or TV app.
2. Click the **Cast / Play On** icon in the navigation bar.
3. Select **"JRiver Media Center"**.
4. Play any video or audio title.
5. JRiver will begin playing the media with full Play, Pause, Unpause, and Seek synchronization on your Jellyfin client.
6. When playback finishes or you press Stop on JRiver, the session releases automatically, allowing another video to be cast immediately.

---

## Compatibility with Non-Jellyfin Cast Apps

### Primary Design & Testing Focus
The primary design, implementation, and multi-clip testing of this project has been focused specifically on **Jellyfin clients casting to JRiver Media Center** using a hybrid architecture: direct Jellyfin WebSocket player registration paired with a Google Cast V2 receiver.

### Compatibility with Other Cast Senders
Because the application implements standard Google Cast V2 protocol components (mDNS Zeroconf advertising on `_googlecast._tcp`, Eureka HTTP service on port 8008, TLS protocol buffers on port 8009, and the standard Cast media namespace `urn:x-cast:com.google.cast.media`), the bridge can also accept streams from generic third-party Cast senders.

When a compatible third-party app casts to "JRiver Media Center", the bridge receives the standard `LOAD` payload, forwards the stream URL to JRiver MCWS via `Playback/PlayByURL`, and relays Play, Pause, Seek, Stop, and Volume adjustments into JRiver with full zone pinning and fullscreen display exit.

#### Expected Working Apps & Use Cases
- **Mobile Cast Utilities (Android / iOS)**: Apps like **BubbleUPnP**, **Web Video Caster**, **LocalCast**, and **AllCast** streaming personal video, audio, or DLNA files directly to JRiver.
- **Desktop Media Players**: Players such as **VLC Media Player** (`Playback` → `Renderer` → `JRiver Media Center`).
- **Web Browsers (Chrome / Edge / Chromium)**: Casting direct HTML5 `<video>` or `<audio>` elements from websites that expose direct, unencrypted media URLs.

#### Known Limitations with Non-Jellyfin Apps
1. **No DRM or Commercial Streaming Services (Netflix, Disney+, Prime Video, Max)**:
   - These services require Google Widevine DRM and run proprietary web receiver apps inside an official Google Chromium receiver.
   - This bridge is a lightweight headless protocol emulator without a Widevine Content Decryption Module (CDM). Encrypted commercial streams are not supported.
2. **Proprietary App Namespaces (YouTube, Spotify)**:
   - **YouTube** uses custom Cast namespaces (`urn:x-cast:com.google.youtube.mdx`) and delegates playback to its own web app rather than sending direct stream URLs.
   - **Spotify** relies on Spotify Connect or encrypted vendor payloads rather than standard Cast V2 media URLs.
3. **Google Hardware Attestation (`deviceauth`)**:
   - Official Chromecast hardware uses proprietary Google-signed private keys for hardware verification. The bridge responds with a standard internal challenge response; while Jellyfin, Chrome, and open cast utilities bypass this check cleanly, some strict Google Play Services applications may enforce hardware verification and decline connection.
4. **Network Stream URL Reachability**:
   - The media URL supplied in the `LOAD` message must be network-accessible from the PC running JRiver. If a mobile app attempts to stream a local sandboxed file via `localhost` without exposing an HTTP endpoint on its LAN IP, JRiver will be unable to retrieve the media.
5. **Session Management Differences**:
   - Jellyfin enjoys **dual-layer integration** (direct server WebSocket session reporting playback progress, direct-stream parameters, and user watch states). Non-Jellyfin apps operate solely across the local Cast V2 socket and will not report progress to an external media server.

---

## Component Directory Structure

```
jellyfin-jriver-bridge/
├── config.example.yaml            # Template configuration (copy to config.yaml)
├── config.yaml                    # Local application settings (ignored by git)
├── requirements.txt               # Python package dependencies
├── build_exe.bat                  # One-click PyInstaller compiler to standalone .exe
├── JRiverCastBridge.spec          # PyInstaller build specification
├── run.py                         # Console / CLI launcher
├── run_tray.py                    # Windows System Tray GUI application
├── start_tray.bat                 # Visible console launcher (shows output & pauses on error)
├── start_tray_silent.bat          # Silent background batch launcher
├── start_tray_silent.vbs          # Zero-window silent background VBS launcher
├── bridge.log                     # Rolling application log (capped at 2,000 lines)
├── certs/                         # Auto-generated TLS certificates for Cast V2
│   ├── cast_bridge.crt
│   └── cast_bridge.key
├── dist/                          # Output directory for compiled standalone .exe
│   ├── JRiverCastBridge.exe
│   ├── config.yaml
│   └── certs/
│       ├── cast_bridge.crt
│       └── cast_bridge.key
└── jellyfin_jriver_bridge/
    ├── __init__.py
    ├── main.py                    # CLI entry point
    ├── service.py                 # Core bridge lifecycle and health check manager
    ├── cert_utils.py              # X.509 TLS certificate generation
    ├── bridge/
    │   └── controller.py          # Command glue layer & status tracking
    ├── cast_receiver/
    │   ├── discovery.py           # mDNS Zeroconf network advertiser
    │   ├── eureka.py              # Port 8008 Eureka HTTP service
    │   ├── server.py              # Port 8009 Cast V2 TLS server
    │   ├── connection.py          # Per-client TLS connection handler
    │   ├── namespaces.py          # Cast namespace message router
    │   └── protocol.py            # Cast V2 protobuf framer
    ├── jellyfin/
    │   └── client.py              # Jellyfin remote control client & WebSocket
    └── jriver/
        └── mcws.py                # JRiver MCWS REST client
```

---

## Troubleshooting

- **Tray icon is Red**:
  - Right-click the tray icon to read the status tooltip.
  - If JRiver is offline: verify JRiver Media Center is open and MCWS is enabled (**Tools → Options → Media Network**).
  - If Jellyfin is offline: verify your `url`, `username`, and `password` in `config.yaml`.
- **Windows Firewall**:
  - Ensure inbound TCP ports `8009` (Cast TLS) and `8008` (Eureka HTTP) are allowed:
    ```powershell
    New-NetFirewallRule -DisplayName "JRiver Cast Bridge" -Direction Inbound -Protocol TCP -LocalPort 8009,8008 -Action Allow
    ```
- **Inspect Live Logs**:
  - Right-click the tray icon and select **View Live Logs**, or open `bridge.log` in the application folder.

---

## License
MIT License
