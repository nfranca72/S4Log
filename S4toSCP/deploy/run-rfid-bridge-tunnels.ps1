param(
    [string]$InstallRoot = "C:\s4-log",
    [string]$BridgeRoot = (Join-Path $InstallRoot "rfid-bridge"),
    [string]$HostAddress = "0.0.0.0",
    [int]$Tunnel1Port = 5001,
    [int]$Tunnel2Port = 5002
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runScript = Join-Path $scriptRoot "run-rfid-bridge.ps1"

Start-Process powershell.exe `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$runScript`"", "-InstallRoot", "`"$InstallRoot`"", "-BridgeRoot", "`"$BridgeRoot`"", "-HostAddress", $HostAddress, "-Port", $Tunnel1Port) `
    -WindowStyle Hidden

Start-Process powershell.exe `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$runScript`"", "-InstallRoot", "`"$InstallRoot`"", "-BridgeRoot", "`"$BridgeRoot`"", "-HostAddress", $HostAddress, "-Port", $Tunnel2Port) `
    -WindowStyle Hidden

"RFID bridge tunnel processes started: $Tunnel1Port, $Tunnel2Port."
