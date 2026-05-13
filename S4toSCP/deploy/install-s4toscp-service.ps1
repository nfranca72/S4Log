param(
    [string]$ServiceName = "S4toSCP",
    [string]$InstallRoot = "C:\s4-log",
    [string]$AppRoot = (Join-Path $InstallRoot "S4toSCP"),
    [string]$NssmPath = "nssm.exe",
    [string]$HostAddress = "0.0.0.0",
    [int]$Port = 8000,
    [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"

$backendDir = Join-Path $AppRoot "wms-scpapp\backend"
$runScript = Join-Path $AppRoot "deploy\run-s4toscp.ps1"
$logsDir = Join-Path $InstallRoot "logs"

New-Item -ItemType Directory -Force $logsDir | Out-Null

$nssm = (Get-Command $NssmPath -ErrorAction Stop).Source

& $nssm install $ServiceName "powershell.exe" "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`" -InstallRoot `"$InstallRoot`" -AppRoot `"$AppRoot`" -HostAddress $HostAddress -Port $Port"
& $nssm set $ServiceName AppDirectory $backendDir
& $nssm set $ServiceName DisplayName "S4toSCP Backend and Frontend"
& $nssm set $ServiceName Description "Runs the S4toSCP FastAPI backend and serves the built frontend."
& $nssm set $ServiceName Start SERVICE_AUTO_START
& $nssm set $ServiceName AppStdout (Join-Path $logsDir "$ServiceName.out.log")
& $nssm set $ServiceName AppStderr (Join-Path $logsDir "$ServiceName.err.log")
& $nssm set $ServiceName AppRotateFiles 1
& $nssm set $ServiceName AppRotateOnline 1
& $nssm set $ServiceName AppRotateBytes 10485760

if ($OpenFirewall) {
    $ruleName = "S4toSCP $Port"
    if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port | Out-Null
    }
}

Start-Service $ServiceName

"Service $ServiceName installed and started on port $Port."
