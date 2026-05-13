param(
    [string]$ServiceName = "S4RfidBridge",
    [string]$InstallRoot = "C:\s4-log",
    [string]$BridgeRoot = (Join-Path $InstallRoot "rfid-bridge"),
    [string]$NssmPath = "nssm.exe",
    [string]$HostAddress = "0.0.0.0",
    [int]$Port = 5000,
    [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"

$appRoot = Join-Path $InstallRoot "S4toSCP"
$runScript = Join-Path $appRoot "deploy\run-rfid-bridge.ps1"
$logsDir = Join-Path $InstallRoot "logs"
$bridgeExe = Join-Path $BridgeRoot "RfidBridge.exe"

if (-not (Test-Path $bridgeExe)) {
    throw "RFID bridge executable not found at $bridgeExe. Copy the published bridge to $BridgeRoot first."
}

New-Item -ItemType Directory -Force $logsDir | Out-Null

$nssm = (Get-Command $NssmPath -ErrorAction Stop).Source

& $nssm install $ServiceName "powershell.exe" "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`" -InstallRoot `"$InstallRoot`" -BridgeRoot `"$BridgeRoot`" -HostAddress $HostAddress -Port $Port"
& $nssm set $ServiceName AppDirectory $BridgeRoot
& $nssm set $ServiceName DisplayName "S4 RFID Bridge"
& $nssm set $ServiceName Description "Runs the S4 RFID bridge that connects to the Zebra reader."
& $nssm set $ServiceName Start SERVICE_AUTO_START
& $nssm set $ServiceName AppStdout (Join-Path $logsDir "$ServiceName.out.log")
& $nssm set $ServiceName AppStderr (Join-Path $logsDir "$ServiceName.err.log")
& $nssm set $ServiceName AppRotateFiles 1
& $nssm set $ServiceName AppRotateOnline 1
& $nssm set $ServiceName AppRotateBytes 10485760

if ($OpenFirewall) {
    $ruleName = "$ServiceName $Port"
    if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port | Out-Null
    }
}

Start-Service $ServiceName

"Service $ServiceName installed and started on port $Port."
