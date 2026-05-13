param(
    [string]$InstallRoot = "C:\s4-log",
    [string]$AppRoot = (Join-Path $InstallRoot "S4toSCP"),
    [string]$HostAddress = "0.0.0.0",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$backendDir = Join-Path $AppRoot "wms-scpapp\backend"
$pythonExe = Join-Path $backendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Python venv not found at $pythonExe. Run deploy\setup-s4toscp.ps1 first."
}

Set-Location $backendDir
& $pythonExe -m uvicorn app.main:app --host $HostAddress --port $Port
