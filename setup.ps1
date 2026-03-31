# =========================================================
# MITMPROXY SMART AUTO SETUP (TWO PHASE MODE)
# Phase 1 → Local Cert Setup (127.0.0.1:8082)
# Phase 2 → Production Agent Mode (Auto-detected IPv4:8082)
# 
# CERTIFICATE: Local Machine (for all users)
# INCLUDES: to-server.py auto-start with Python detection
# =========================================================

$ErrorActionPreference = "Stop"

# ---------------------------
# Configuration
# ---------------------------
$BaseDir      = "C:\mitm-auto"
$AgentPath    = "$BaseDir\agent.py"
$ToServerPath = "$BaseDir\to-server.py"

# Phase 1 (LOCAL CERT MODE)
$Phase1IP     = "127.0.0.1"
$Phase1Port   = 8082

# Phase 2 (PRODUCTION MODE)
# ---------------------------
# Auto-detect active IPv4 (Wi-Fi / Ethernet)
# ---------------------------
function Get-ActiveIPv4 {
    $ip = Get-NetIPAddress `
        -AddressFamily IPv4 `
        -PrefixOrigin Dhcp `
        -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -ne "127.0.0.1" -and
            $_.IPAddress -notlike "169.254.*"
        } |
        Sort-Object InterfaceMetric |
        Select-Object -First 1 -ExpandProperty IPAddress

    if (-not $ip) {
        Write-Host "ERROR: No active IPv4 address detected" -ForegroundColor Red
        exit 1
    }

    return $ip
}

# ---------------------------
# Auto-detect Python executable
# ---------------------------
function Get-PythonPath {
    # Try common locations
    $pythonPaths = @(
        "python",
        "python3",
        "py",
        "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe",
        "$env:PROGRAMFILES\Python*\python.exe",
        "$env:PROGRAMFILES(x86)\Python*\python.exe",
        "$env:USERPROFILE\AppData\Local\Programs\Python\Python*\python.exe"
    )

    # First try command-line accessible python
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $result = & $cmd --version 2>&1
            if ($result -match "Python") {
                Write-Host "[OK] Found Python via command: $cmd" -ForegroundColor Green
                return $cmd
            }
        }
        catch {
            # Continue searching
        }
    }

    # Search filesystem for python.exe
    foreach ($path in $pythonPaths) {
        if ($path -like "*\*") {
            $found = Get-ChildItem $path -ErrorAction SilentlyContinue | 
                     Sort-Object LastWriteTime -Descending | 
                     Select-Object -First 1

            if ($found) {
                Write-Host "[OK] Found Python at: $($found.FullName)" -ForegroundColor Green
                return $found.FullName
            }
        }
    }

    Write-Host "[WARNING] Python not found automatically" -ForegroundColor Yellow
    return $null
}

$Phase2IP = Get-ActiveIPv4
$Phase2Port   = 8082

$AgentRawUrl  = "https://raw.githubusercontent.com/MonishKuril/Url_and_content_filtering/main/agent.py"
$ToServerRawUrl = "https://raw.githubusercontent.com/MonishKuril/Url_and_content_filtering/main/to-server.py"
$InstallerUrl = "https://downloads.mitmproxy.org/10.2.4/mitmproxy-10.2.4-windows-x86_64-installer.exe"
$Installer    = "$env:TEMP\mitmproxy-installer.exe"

$MaxWaitSeconds = 600
$ScanInterval   = 5

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  MITMPROXY SMART AUTO SETUP" -ForegroundColor Cyan
Write-Host "  Version: Local Machine Certificate" -ForegroundColor Cyan
Write-Host "  + to-server.py Integration" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------
# 1. Ensure Working Folder
# ---------------------------
if (!(Test-Path $BaseDir)) {
    New-Item -ItemType Directory -Path $BaseDir | Out-Null
    Write-Host "[OK] Created directory: $BaseDir" -ForegroundColor Green
}

# ---------------------------
# 2. Detect Python
# ---------------------------
Write-Host ""
Write-Host "Detecting Python installation..." -ForegroundColor Yellow
$PythonExe = Get-PythonPath

if (-not $PythonExe) {
    Write-Host ""
    Write-Host "=================================================" -ForegroundColor Red
    Write-Host "  PYTHON NOT FOUND!" -ForegroundColor Red
    Write-Host "=================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Python from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "During installation, make sure to check:" -ForegroundColor Yellow
    Write-Host "  Add Python to PATH" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Or manually enter Python path below" -ForegroundColor Cyan
    Write-Host "Example: C:\Python39\python.exe" -ForegroundColor Cyan
    Write-Host ""
    
    $manualPath = Read-Host "Enter Python executable path (or press ENTER to skip to-server.py)"
    
    if ([string]::IsNullOrWhiteSpace($manualPath)) {
        Write-Host "[WARNING] Skipping to-server.py startup" -ForegroundColor Yellow
        $PythonExe = $null
    }
    else {
        if (Test-Path $manualPath) {
            $PythonExe = $manualPath
            Write-Host "[OK] Using Python at: $PythonExe" -ForegroundColor Green
        }
        else {
            Write-Host "[WARNING] Path not found. Skipping to-server.py startup" -ForegroundColor Yellow
            $PythonExe = $null
        }
    }
}

# ---------------------------
# 3. Ask for GitHub Token
# ---------------------------
Write-Host ""
Write-Host "GitHub Authentication Required" -ForegroundColor Yellow
$tokenSecure = Read-Host "Enter your GitHub Personal Access Token" -AsSecureString
$tokenPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($tokenSecure)
$GitHubToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPtr)

if ([string]::IsNullOrWhiteSpace($GitHubToken)) {
    Write-Host "[ERROR] GitHub token cannot be empty" -ForegroundColor Red
    exit 1
}

# ---------------------------
# 4. Download agent.py
# ---------------------------
Write-Host ""
Write-Host "Downloading agent.py from private repository..." -ForegroundColor Yellow

$Headers = @{
    Authorization = "token $GitHubToken"
    "User-Agent"  = "PowerShell"
}

try {
    Invoke-WebRequest -Uri $AgentRawUrl -Headers $Headers -OutFile $AgentPath
    if (!(Test-Path $AgentPath)) {
        Write-Host "[ERROR] agent.py download failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] agent.py downloaded successfully" -ForegroundColor Green
}
catch {
    Write-Host "[ERROR] Failed to download agent.py - $_" -ForegroundColor Red
    exit 1
}

# ---------------------------
# 5. Download to-server.py
# ---------------------------
Write-Host ""
Write-Host "Downloading to-server.py from private repository..." -ForegroundColor Yellow

try {
    Invoke-WebRequest -Uri $ToServerRawUrl -Headers $Headers -OutFile $ToServerPath
    if (!(Test-Path $ToServerPath)) {
        Write-Host "[ERROR] to-server.py download failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] to-server.py downloaded successfully" -ForegroundColor Green
}
catch {
    Write-Host "[ERROR] Failed to download to-server.py - $_" -ForegroundColor Red
    exit 1
}

# ---------------------------
# 6. Download mitmproxy Installer
# ---------------------------
if (!(Test-Path $Installer)) {
    Write-Host "Downloading mitmproxy installer..." -ForegroundColor Yellow
    try {
        Invoke-WebRequest -Uri $InstallerUrl -OutFile $Installer
        Write-Host "[OK] Installer downloaded" -ForegroundColor Green
    }
    catch {
        Write-Host "[ERROR] Failed to download installer - $_" -ForegroundColor Red
        exit 1
    }
}
else {
    Write-Host "[OK] Installer already exists" -ForegroundColor Green
}

# ---------------------------
# 7. Launch Installer
# ---------------------------
Write-Host ""
Write-Host "Launching mitmproxy installer..." -ForegroundColor Yellow
Start-Process -FilePath $Installer
Write-Host "Please complete the installer window manually." -ForegroundColor Cyan

# ---------------------------
# 8. Wait Until mitmdump.exe Appears
# ---------------------------
Write-Host "Waiting for mitmproxy installation to complete..." -ForegroundColor Yellow

$elapsed = 0
$MitmExe = $null

$searchPaths = @(
    "C:\Program Files",
    "C:\Program Files (x86)",
    "$env:LOCALAPPDATA"
)

while ($elapsed -lt $MaxWaitSeconds) {

    foreach ($path in $searchPaths) {
        $found = Get-ChildItem $path -Recurse -Filter "mitmdump.exe" -ErrorAction SilentlyContinue |
                 Select-Object -First 1

        if ($found) {
            $MitmExe = $found.FullName
            break
        }
    }

    if ($MitmExe) { break }

    Start-Sleep -Seconds $ScanInterval
    $elapsed += $ScanInterval
    Write-Host "  Waiting... $elapsed / $MaxWaitSeconds sec" -ForegroundColor Gray
}

if (-not $MitmExe) {
    Write-Host "[ERROR] mitmdump not detected. Please finish installation and rerun." -ForegroundColor Red
    exit 1
}

Write-Host "[OK] mitmdump detected at: $MitmExe" -ForegroundColor Green

# ---------------------------
# 9. Phase 1 Proxy (Local Cert Mode)
# ---------------------------
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  PHASE 1: Certificate Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"

Set-ItemProperty -Path $regPath -Name ProxyEnable -Value 1
Set-ItemProperty -Path $regPath -Name ProxyServer -Value "${Phase1IP}:$Phase1Port"
Set-ItemProperty -Path $regPath -Name AutoDetect -Value 0

Write-Host "[OK] Proxy configured: ${Phase1IP}:$Phase1Port" -ForegroundColor Green

# ---------------------------
# 10. Start mitmdump (Certificate Setup Mode)
# ---------------------------
Write-Host ""
Write-Host "Starting mitmdump for certificate installation..." -ForegroundColor Yellow
Write-Host "A PowerShell window will open showing mitmdump logs..." -ForegroundColor Cyan

$command1 = "& '$MitmExe' --listen-host 0.0.0.0 --listen-port $Phase1Port"
Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-Command", $command1

Start-Sleep -Seconds 3
Start-Process "http://mitm.it"

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Yellow
Write-Host "  CRITICAL: CERTIFICATE INSTALLATION INSTRUCTIONS" -ForegroundColor Yellow
Write-Host "=============================================================" -ForegroundColor Yellow
Write-Host ""
Write-Host " 1. Browser should have opened http://mitm.it" -ForegroundColor White
Write-Host " 2. Click on your platform (Windows)" -ForegroundColor White
Write-Host " 3. Download the certificate file" -ForegroundColor White
Write-Host ""
Write-Host " 4. IMPORTANT - When installing:" -ForegroundColor Red
Write-Host "    -> Select 'LOCAL MACHINE' (NOT Current User)" -ForegroundColor Red
Write-Host "    -> Place in 'Trusted Root Certification Authorities'" -ForegroundColor Red
Write-Host ""
Write-Host " 5. Double-click the downloaded .cer file" -ForegroundColor White
Write-Host " 6. Click 'Install Certificate'" -ForegroundColor White
Write-Host " 7. Choose 'Local Machine' -> Click 'Next'" -ForegroundColor White
Write-Host " 8. Select 'Place all certificates in the following store'" -ForegroundColor White
Write-Host " 9. Click 'Browse' -> Choose 'Trusted Root Certification Authorities'" -ForegroundColor White
Write-Host "10. Click 'Next' -> 'Finish'" -ForegroundColor White
Write-Host ""
Write-Host "=============================================================" -ForegroundColor Yellow

Write-Host ""
Read-Host "Press ENTER once you have installed the certificate"

# ---------------------------
# 11. Stop Phase-1 Process
# ---------------------------
Write-Host ""
Write-Host "Stopping Phase 1 proxy..." -ForegroundColor Yellow
Get-Process -Name "mitmdump" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
Write-Host "[OK] Phase 1 stopped" -ForegroundColor Green

# ---------------------------
# 12. Phase 2 Proxy (Production Mode)
# ---------------------------
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  PHASE 2: Production Agent Mode" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Detected Active IP: $Phase2IP" -ForegroundColor Green

Set-ItemProperty -Path $regPath -Name ProxyServer -Value "${Phase2IP}:$Phase2Port"
Write-Host "[OK] Proxy updated to: ${Phase2IP}:$Phase2Port" -ForegroundColor Green

Write-Host ""
Write-Host "Starting production agent..." -ForegroundColor Yellow

$command2 = "& '$MitmExe' --listen-host 0.0.0.0 --listen-port $Phase2Port -s '$AgentPath'"
Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-Command", $command2

Start-Sleep -Seconds 3

# ---------------------------
# 13. Start to-server.py
# ---------------------------
if ($PythonExe) {
    Write-Host ""
    Write-Host "Starting to-server.py..." -ForegroundColor Yellow

    $command3 = "& '$PythonExe' '$ToServerPath'"
    Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-Command", $command3

    Start-Sleep -Seconds 2
    Write-Host "[OK] to-server.py started in separate terminal" -ForegroundColor Green
}
else {
    Write-Host ""
    Write-Host "[SKIPPED] to-server.py not started (Python not found)" -ForegroundColor Yellow
    Write-Host "You can start it manually later with:" -ForegroundColor Cyan
    Write-Host "  python $ToServerPath" -ForegroundColor White
}

# ---------------------------
# FINAL STATUS
# ---------------------------
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  SETUP COMPLETED SUCCESSFULLY!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Configuration:" -ForegroundColor Cyan
Write-Host "  Proxy Address  : ${Phase2IP}:$Phase2Port" -ForegroundColor White
Write-Host "  Agent Script   : $AgentPath" -ForegroundColor White
Write-Host "  Server Script  : $ToServerPath" -ForegroundColor White
Write-Host "  Certificate    : Local Machine Store" -ForegroundColor White
Write-Host ""
Write-Host "Running Processes:" -ForegroundColor Cyan
Write-Host "  - mitmproxy agent (PowerShell window)" -ForegroundColor White

if ($PythonExe) {
    Write-Host "  - to-server.py (PowerShell window)" -ForegroundColor White
}
else {
    Write-Host "  - to-server.py (NOT RUNNING - Python not found)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "The proxy and server will stop if you close their PowerShell windows." -ForegroundColor Yellow
Write-Host ""
