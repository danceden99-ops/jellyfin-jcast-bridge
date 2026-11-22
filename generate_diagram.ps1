Add-Type -AssemblyName System.Drawing

$width = 2400
$height = 1350

$bmp = [System.Drawing.Bitmap]::new($width, $height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic

# Color Palette
$bgColor = [System.Drawing.ColorTranslator]::FromHtml("#0B0F19")
$panelBg = [System.Drawing.ColorTranslator]::FromHtml("#131B2E")
$subPanelBg = [System.Drawing.ColorTranslator]::FromHtml("#1E293B")
$borderColor = [System.Drawing.ColorTranslator]::FromHtml("#2A374E")

$cyanAccent = [System.Drawing.ColorTranslator]::FromHtml("#38BDF8")
$purpleAccent = [System.Drawing.ColorTranslator]::FromHtml("#C084FC")
$emeraldAccent = [System.Drawing.ColorTranslator]::FromHtml("#34D399")
$amberAccent = [System.Drawing.ColorTranslator]::FromHtml("#FBBF24")
$roseAccent = [System.Drawing.ColorTranslator]::FromHtml("#F43F5E")
$textLight = [System.Drawing.ColorTranslator]::FromHtml("#F8FAFC")
$textMuted = [System.Drawing.ColorTranslator]::FromHtml("#94A3B8")

$g.Clear($bgColor)

# Subtle background grid
$gridPen = [System.Drawing.Pen]::new([System.Drawing.ColorTranslator]::FromHtml("#141D2E"), 1)
for ($x = 0; $x -lt $width; $x += 60) {
    $g.DrawLine($gridPen, [int]$x, 0, [int]$x, $height)
}
for ($y = 0; $y -lt $height; $y += 60) {
    $g.DrawLine($gridPen, 0, [int]$y, $width, [int]$y)
}
$gridPen.Dispose()

# Helper function to draw rounded rectangles
function Draw-RoundedRect([System.Drawing.Graphics]$graphics, [System.Drawing.Brush]$brush, [System.Drawing.Pen]$pen, [System.Drawing.Rectangle]$rect, [int]$radius) {
    $path = [System.Drawing.Drawing2D.GraphicsPath]::new()
    $d = $radius * 2
    $path.AddArc($rect.X, $rect.Y, $d, $d, 180, 90)
    $path.AddArc($rect.Right - $d, $rect.Y, $d, $d, 270, 90)
    $path.AddArc($rect.Right - $d, $rect.Bottom - $d, $d, $d, 0, 90)
    $path.AddArc($rect.X, $rect.Bottom - $d, $d, $d, 90, 90)
    $path.CloseFigure()
    
    if ($brush -ne $null) { $graphics.FillPath($brush, $path) }
    if ($pen -ne $null) { $graphics.DrawPath($pen, $path) }
    $path.Dispose()
}

# Helper function to draw badge
function Draw-BadgeBox([System.Drawing.Graphics]$graphics, [string]$title, [string]$subtitle, [int]$bx, [int]$by, [int]$bw, [int]$bh, [System.Drawing.Color]$borderColor, [System.Drawing.Brush]$titleBrush, [System.Drawing.Brush]$subBrush) {
    $rect = [System.Drawing.Rectangle]::new($bx, $by, $bw, $bh)
    $bBrush = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml("#0E1626"))
    $bPen = [System.Drawing.Pen]::new($borderColor, 1.8)
    Draw-RoundedRect $graphics $bBrush $bPen $rect 8
    
    $fT = [System.Drawing.Font]::new("Segoe UI", 10.5, [System.Drawing.FontStyle]::Bold)
    $fS = [System.Drawing.Font]::new("Segoe UI", 8.8, [System.Drawing.FontStyle]::Regular)
    
    $graphics.DrawString($title, $fT, $titleBrush, ($bx + 12), ($by + 7))
    if ($subtitle) {
        $graphics.DrawString($subtitle, $fS, $subBrush, ($bx + 12), ($by + 28))
    }
    
    $fT.Dispose()
    $fS.Dispose()
    $bBrush.Dispose()
    $bPen.Dispose()
}

# Fonts
$fontTitle = [System.Drawing.Font]::new("Segoe UI", 26, [System.Drawing.FontStyle]::Bold)
$fontSubtitle = [System.Drawing.Font]::new("Segoe UI", 13.5, [System.Drawing.FontStyle]::Regular)
$fontHeader = [System.Drawing.Font]::new("Segoe UI", 15, [System.Drawing.FontStyle]::Bold)
$fontSubHeader = [System.Drawing.Font]::new("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
$fontBody = [System.Drawing.Font]::new("Segoe UI", 10.5, [System.Drawing.FontStyle]::Regular)
$fontSmall = [System.Drawing.Font]::new("Segoe UI", 9.8, [System.Drawing.FontStyle]::Regular)

# ── 1. Top Header Banner ─────────────────────────────────────────────────────
$brushTitle = [System.Drawing.SolidBrush]::new($textLight)
$brushMuted = [System.Drawing.SolidBrush]::new($textMuted)
$brushCyan = [System.Drawing.SolidBrush]::new($cyanAccent)
$brushPurple = [System.Drawing.SolidBrush]::new($purpleAccent)
$brushEmerald = [System.Drawing.SolidBrush]::new($emeraldAccent)
$brushAmber = [System.Drawing.SolidBrush]::new($amberAccent)
$brushRose = [System.Drawing.SolidBrush]::new($roseAccent)

$g.DrawString("JELLYFIN CAST -> JRIVER MEDIA CENTER BRIDGE", $fontTitle, $brushTitle, 80, 35)
$g.DrawString("End-to-End System Architecture: Client Casting, Bridge Control Layer & Direct High-Bandwidth Media Stream Routing", $fontSubtitle, $brushMuted, 82, 88)

# Legend Box at Top-Right
$legendRect = [System.Drawing.Rectangle]::new(1620, 38, 700, 85)
$brushLegendBg = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml("#111827"))
$penLegend = [System.Drawing.Pen]::new($borderColor, 1.2)
Draw-RoundedRect $g $brushLegendBg $penLegend $legendRect 8

$penCtrlLeg = [System.Drawing.Pen]::new($cyanAccent, 3)
$g.DrawLine($penCtrlLeg, 1645, 68, 1695, 68)
$g.DrawString("Control, WebSocket & Discovery Protocols (Low Bandwidth)", $fontSmall, $brushTitle, 1705, 60)

$penStreamLeg = [System.Drawing.Pen]::new($roseAccent, 4.5)
$penStreamLeg.DashStyle = [System.Drawing.Drawing2D.DashStyle]::Dash
$g.DrawLine($penStreamLeg, 1645, 96, 1695, 96)
$g.DrawString("Direct Video/Audio Media Stream (High-Bandwidth Direct Pipeline)", $fontSmall, $brushTitle, 1705, 88)

# ── 2. Node 1: Jellyfin Client (Top Left) ────────────────────────────────────
$clientRect = [System.Drawing.Rectangle]::new(80, 160, 540, 360)
$brushPanel = [System.Drawing.SolidBrush]::new($panelBg)
$penClient = [System.Drawing.Pen]::new($cyanAccent, 2)
Draw-RoundedRect $g $brushPanel $penClient $clientRect 12

$clientHdrRect = [System.Drawing.Rectangle]::new(80, 160, 540, 55)
$brushClientHdr = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml("#0C4A6E"))
Draw-RoundedRect $g $brushClientHdr $null $clientHdrRect 12
$g.DrawString("JELLYFIN CAST SENDER / CLIENT", $fontHeader, $brushCyan, 105, 175)

$clientLines = @(
    "Devices: Web Browser (Chrome/Edge), Android, iOS, Android TV",
    "",
    "• Automatically discovers 'JRiver Media Center' in Cast menu",
    "• Negotiates Google Cast V2 receiver handshake over TLS",
    "• Dispatches user playback commands (Play, Pause, Seek, Stop)",
    "• Receives real-time playback position, timeline, and duration",
    "• Controls master volume and dynamic zone muting"
)
$y = 232
foreach ($line in $clientLines) {
    if ($line.StartsWith("•")) {
        $g.DrawString($line, $fontBody, $brushTitle, 105, $y)
    } elseif ($line -eq "") {
        # spacer
    } else {
        $g.DrawString($line, $fontSmall, $brushMuted, 105, $y)
    }
    $y += 28
}

# ── 3. Node 2: Jellyfin Media Server (Top Right) ────────────────────────────
$serverRect = [System.Drawing.Rectangle]::new(1780, 160, 540, 360)
$penServer = [System.Drawing.Pen]::new($purpleAccent, 2)
Draw-RoundedRect $g $brushPanel $penServer $serverRect 12

$serverHdrRect = [System.Drawing.Rectangle]::new(1780, 160, 540, 55)
$brushServerHdr = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml("#4A044E"))
Draw-RoundedRect $g $brushServerHdr $null $serverHdrRect 12
$g.DrawString("JELLYFIN MEDIA SERVER", $fontHeader, $brushPurple, 1805, 175)

$serverLines = @(
    "Host: Local Network Server (Port 8096 / HTTPS)",
    "",
    "• Houses media libraries (Movies, TV Shows, 4K HDR, Audio)",
    "• Maintains active remote sessions via WebSocket (/socket)",
    "• Formulates DirectStream URLs (stream.mkv?static=true)",
    "• Serves high-bitrate media files directly over HTTP / LAN",
    "• Synchronizes user watch marks, resume points, and scrobbling"
)
$y = 232
foreach ($line in $serverLines) {
    if ($line.StartsWith("•")) {
        $g.DrawString($line, $fontBody, $brushTitle, 1805, $y)
    } elseif ($line -eq "") {
        # spacer
    } else {
        $g.DrawString($line, $fontSmall, $brushMuted, 1805, $y)
    }
    $y += 28
}

# ── 4. Node 3: JRiver Cast Bridge (Bottom Left) ──────────────────────────────
$bridgeRect = [System.Drawing.Rectangle]::new(80, 680, 960, 600)
$penBridge = [System.Drawing.Pen]::new($emeraldAccent, 2)
Draw-RoundedRect $g $brushPanel $penBridge $bridgeRect 12

$bridgeHdrRect = [System.Drawing.Rectangle]::new(80, 680, 960, 55)
$brushBridgeHdr = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml("#064E3B"))
Draw-RoundedRect $g $brushBridgeHdr $null $bridgeHdrRect 12
$g.DrawString("JRIVER CAST BRIDGE (Windows System Tray Service / Standalone .exe)", $fontHeader, $brushEmerald, 105, 695)

$brushSubPanel = [System.Drawing.SolidBrush]::new($subPanelBg)
$penSubBorder = [System.Drawing.Pen]::new($borderColor, 1)

# Sub 3A: Cast V2 & Eureka
$sub3ARect = [System.Drawing.Rectangle]::new(110, 755, 430, 225)
Draw-RoundedRect $g $brushSubPanel $penSubBorder $sub3ARect 8
$g.DrawString("Google Cast V2 TLS & Eureka", $fontSubHeader, $brushCyan, 125, 770)
$g.DrawString("• Eureka HTTP Server: Port 8008 (/setup/eureka_info)", $fontSmall, $brushTitle, 125, 805)
$g.DrawString("• Cast V2 TLS Server: Port 8009 (Protobuf Framing)", $fontSmall, $brushTitle, 125, 835)
$g.DrawString("• Namespaces: connection, heartbeat, receiver, media", $fontSmall, $brushTitle, 125, 865)
$g.DrawString("• Handles Chromecast authentication & status responses", $fontSmall, $brushTitle, 125, 895)
$g.DrawString("• Auto-generates 10-year self-signed TLS credentials", $fontSmall, $brushTitle, 125, 925)

# Sub 3B: mDNS Advertiser
$sub3BRect = [System.Drawing.Rectangle]::new(565, 755, 445, 225)
Draw-RoundedRect $g $brushSubPanel $penSubBorder $sub3BRect 8
$g.DrawString("mDNS Discovery Advertiser", $fontSubHeader, $brushCyan, 580, 770)
$g.DrawString("• AsyncZeroconf mDNS advertisement", $fontSmall, $brushTitle, 580, 805)
$g.DrawString("• Service Type: _googlecast._tcp.local.", $fontSmall, $brushTitle, 580, 835)
$g.DrawString("• TXT Flags: id, ve=05, md=Chromecast, ca=4101", $fontSmall, $brushTitle, 580, 865)
$g.DrawString("• Broadcasts device name 'JRiver Media Center'", $fontSmall, $brushTitle, 580, 895)
$g.DrawString("• Auto-detects primary LAN IP for interface binding", $fontSmall, $brushTitle, 580, 925)

# Sub 3C: Jellyfin Remote Client
$sub3CRect = [System.Drawing.Rectangle]::new(110, 1005, 430, 245)
Draw-RoundedRect $g $brushSubPanel $penSubBorder $sub3CRect 8
$g.DrawString("Jellyfin Remote Session Client", $fontSubHeader, $brushPurple, 125, 1020)
$g.DrawString("• REST AuthenticateByName / Token Header", $fontSmall, $brushTitle, 125, 1055)
$g.DrawString("• /Sessions/Capabilities/Full player registration", $fontSmall, $brushTitle, 125, 1085)
$g.DrawString("• Persistent bidirectional WebSocket /socket client", $fontSmall, $brushTitle, 125, 1115)
$g.DrawString("• Ping-pong loop prevention & keep-alive monitor", $fontSmall, $brushTitle, 125, 1145)
$g.DrawString("• Reports live /Sessions/Playing progress & state", $fontSmall, $brushTitle, 125, 1175)
$g.DrawString("• Auto-stops previous session on new media switch", $fontSmall, $brushTitle, 125, 1205)

# Sub 3D: Bridge Controller & Zone Engine
$sub3DRect = [System.Drawing.Rectangle]::new(565, 1005, 445, 245)
Draw-RoundedRect $g $brushSubPanel $penSubBorder $sub3DRect 8
$g.DrawString("Bridge Controller & Zone Pinning", $fontSubHeader, $brushEmerald, 580, 1020)
$g.DrawString("• Concrete Zone ID Pinning (Zone ID=0 'Player')", $fontSmall, $brushTitle, 580, 1055)
$g.DrawString("• Maps Cast verbs to JRiver MCWS REST endpoints", $fontSmall, $brushTitle, 580, 1085)
$g.DrawString("• Issues 'Escape' on Stop to exit Display View GUI", $fontSmall, $brushTitle, 580, 1115)
$g.DrawString("• Applies user find/replace URL rewriting rules", $fontSmall, $brushTitle, 580, 1145)
$g.DrawString("• System Tray UI (Green/Red/Amber status icons)", $fontSmall, $brushTitle, 580, 1175)
$g.DrawString("• Rolling 2,000-line capped disk logging (bridge.log)", $fontSmall, $brushTitle, 580, 1205)

# ── 5. Node 4: JRiver Media Center (Bottom Right) ────────────────────────────
$jriverRect = [System.Drawing.Rectangle]::new(1360, 680, 960, 600)
$penJRiver = [System.Drawing.Pen]::new($amberAccent, 2)
Draw-RoundedRect $g $brushPanel $penJRiver $jriverRect 12

$jriverHdrRect = [System.Drawing.Rectangle]::new(1360, 680, 960, 55)
$brushJRiverHdr = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml("#78350F"))
Draw-RoundedRect $g $brushJRiverHdr $null $jriverHdrRect 12
$g.DrawString("JRIVER MEDIA CENTER (Media Player, Decoders & Output Renderer)", $fontHeader, $brushAmber, 1385, 695)

# Sub 4A: MCWS Interface
$sub4ARect = [System.Drawing.Rectangle]::new(1390, 755, 440, 225)
Draw-RoundedRect $g $brushSubPanel $penSubBorder $sub4ARect 8
$g.DrawString("MCWS Web Service (Port 52199)", $fontSubHeader, $brushAmber, 1405, 770)
$g.DrawString("• REST API: /MCWS/v1/", $fontSmall, $brushTitle, 1405, 805)
$g.DrawString("• Playback/PlayByURL?URL=... (Starts playback)", $fontSmall, $brushTitle, 1405, 835)
$g.DrawString("• Playback/Pause (Toggles play/pause states)", $fontSmall, $brushTitle, 1405, 865)
$g.DrawString("• Playback/Position?Position=... (Exact seek ms)", $fontSmall, $brushTitle, 1405, 895)
$g.DrawString("• Playback/Stop & UserControl/Key?Key=Escape", $fontSmall, $brushTitle, 1405, 925)

# Sub 4B: Video Engine & Splitter
$sub4BRect = [System.Drawing.Rectangle]::new(1855, 755, 435, 225)
Draw-RoundedRect $g $brushSubPanel $penSubBorder $sub4BRect 8
$g.DrawString("DirectShow / LAV Video Engine", $fontSubHeader, $brushRose, 1870, 770)
$g.DrawString("• DirectShow Network Source & Splitter", $fontSmall, $brushTitle, 1870, 805)
$g.DrawString("• LAV Filters (H.264, HEVC / H.265, AV1, VP9)", $fontSmall, $brushTitle, 1870, 835)
$g.DrawString("• Custom GLSL Shaders & madVR Video Processing", $fontSmall, $brushTitle, 1870, 865)
$g.DrawString("• BT.2020 PQ HDR Output & Target-Peak Tone Mapping", $fontSmall, $brushTitle, 1870, 895)
$g.DrawString("• Clean Display View fullscreen playback", $fontSmall, $brushTitle, 1870, 925)

# Sub 4C: Audio Engine
$sub4CRect = [System.Drawing.Rectangle]::new(1390, 1005, 900, 245)
Draw-RoundedRect $g $brushSubPanel $penSubBorder $sub4CRect 8
$g.DrawString("Bit-Perfect Audio & Display Engine", $fontSubHeader, $brushAmber, 1405, 1020)
$g.DrawString("• WASAPI Exclusive & ASIO Direct Hardware Output (Zero Windows Resampling)", $fontSmall, $brushTitle, 1405, 1060)
$g.DrawString("• Bitstreaming: Dolby Atmos, TrueHD, DTS-HD Master Audio, multichannel FLAC/PCM", $fontSmall, $brushTitle, 1405, 1095)
$g.DrawString("• High-Precision Master Volume & Dynamic DRC management", $fontSmall, $brushTitle, 1405, 1130)
$g.DrawString("• Full integration with calibrated 4K home theater projectors and audiophile DACs", $fontSmall, $brushTitle, 1405, 1165)

# ── 6. Interconnecting Arrows & Badges ───────────────────────────────────────
$cap = [System.Drawing.Drawing2D.AdjustableArrowCap]::new(6, 6, $true)

# --- Connection 1: Client -> Bridge (Cast Control) ---
$penCast = [System.Drawing.Pen]::new($cyanAccent, 3)
$penCast.CustomEndCap = $cap
$g.DrawLine($penCast, 260, 520, 260, 680)
Draw-BadgeBox $g "Google Cast V2 Protocol (TLS :8009)" "LOAD, PLAY, PAUSE, SEEK, STOP, VOLUME (Protobuf)" 90 575 340 50 $cyanAccent $brushCyan $brushTitle

# --- Connection 2: Bridge -> Client (Discovery) ---
$penDisc = [System.Drawing.Pen]::new($cyanAccent, 2)
$penDisc.DashStyle = [System.Drawing.Drawing2D.DashStyle]::Dot
$penDisc.CustomEndCap = $cap
$g.DrawLine($penDisc, 460, 680, 460, 520)
Draw-BadgeBox $g "mDNS & Eureka Setup (:8008)" "Device discovery & Cast handshake" 445 575 220 50 $cyanAccent $brushCyan $brushTitle

# --- Connection 3: Bridge <-> Jellyfin Server (WebSocket & Session) ---
$penWs = [System.Drawing.Pen]::new($purpleAccent, 3.5)
$penWs.CustomEndCap = $cap
[System.Drawing.Point[]]$pointsWs = @(
    [System.Drawing.Point]::new(800, 680),
    [System.Drawing.Point]::new(800, 590),
    [System.Drawing.Point]::new(1840, 590),
    [System.Drawing.Point]::new(1840, 520)
)
$g.DrawLines($penWs, $pointsWs)
Draw-BadgeBox $g "Jellyfin Remote Player WebSocket & REST (Port 8096)" "Keep-Alive Heartbeats, Playback Capabilities & /Sessions/Playing/Progress" 1050 565 470 50 $purpleAccent $brushPurple $brushTitle

# --- Connection 4: Bridge -> JRiver MCWS (Commands) ---
$penMcws = [System.Drawing.Pen]::new($amberAccent, 3.5)
$penMcws.CustomEndCap = $cap
$g.DrawLine($penMcws, 1040, 840, 1360, 840)
Draw-BadgeBox $g "MCWS REST Control (Port 52199)" "Playback/PlayByURL (Zone 0), Pause, Seek, Escape" 1055 865 290 50 $amberAccent $brushAmber $brushTitle

# --- Connection 5: DIRECT MEDIA STREAM (Server -> JRiver) ---
$penStream = [System.Drawing.Pen]::new($roseAccent, 6)
$penStream.CustomEndCap = $cap
$g.DrawLine($penStream, 2080, 520, 2080, 755)
Draw-BadgeBox $g "DIRECT MEDIA STREAM (Bypasses Bridge!)" "HTTP / HTTPS / HLS / Direct UNC (Zero Bridge Bottleneck)" 1880 575 350 50 $roseAccent $brushRose $brushTitle

# Save bitmap
$outputPath = "Z:\jellyfin-jriver-bridge\architecture_overview.png"
$bmp.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)
Write-Output "Successfully generated: $outputPath"

$g.Dispose()
$bmp.Dispose()
