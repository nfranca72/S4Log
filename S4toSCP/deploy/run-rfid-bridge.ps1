param(
    [string]$InstallRoot = "C:\s4-log",
    [string]$BridgeRoot = (Join-Path $InstallRoot "rfid-bridge"),
    [string]$HostAddress = "0.0.0.0",
    [int]$Port = 5000
)

$ErrorActionPreference = "Stop"

$bridgeExe = Join-Path $BridgeRoot "RfidBridge.exe"
if (-not (Test-Path $bridgeExe)) {
    throw "RFID bridge executable not found at $bridgeExe."
}

Set-Location $BridgeRoot
& $bridgeExe --urls "http://$HostAddress`:$Port"
