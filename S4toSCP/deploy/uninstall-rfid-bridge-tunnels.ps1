param(
    [string]$NssmPath = "nssm.exe"
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$uninstallScript = Join-Path $scriptRoot "uninstall-rfid-bridge-service.ps1"

& $uninstallScript -ServiceName "S4RfidBridgeTunnel1" -NssmPath $NssmPath
& $uninstallScript -ServiceName "S4RfidBridgeTunnel2" -NssmPath $NssmPath

"RFID bridge tunnel services removed."
