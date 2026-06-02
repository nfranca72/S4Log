param(
    [string]$InstallRoot = "C:\s4-log",
    [string]$BridgeRoot = (Join-Path $InstallRoot "rfid-bridge"),
    [string]$NssmPath = "nssm.exe",
    [string]$HostAddress = "0.0.0.0",
    [int]$Tunnel1Port = 5001,
    [int]$Tunnel2Port = 5002,
    [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$installScript = Join-Path $scriptRoot "install-rfid-bridge-service.ps1"

& $installScript `
    -ServiceName "S4RfidBridgeTunnel1" `
    -InstallRoot $InstallRoot `
    -BridgeRoot $BridgeRoot `
    -NssmPath $NssmPath `
    -HostAddress $HostAddress `
    -Port $Tunnel1Port `
    -OpenFirewall:$OpenFirewall

& $installScript `
    -ServiceName "S4RfidBridgeTunnel2" `
    -InstallRoot $InstallRoot `
    -BridgeRoot $BridgeRoot `
    -NssmPath $NssmPath `
    -HostAddress $HostAddress `
    -Port $Tunnel2Port `
    -OpenFirewall:$OpenFirewall

"RFID bridge tunnel services installed: S4RfidBridgeTunnel1=$Tunnel1Port, S4RfidBridgeTunnel2=$Tunnel2Port."
