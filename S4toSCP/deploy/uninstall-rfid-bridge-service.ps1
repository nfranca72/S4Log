param(
    [string]$ServiceName = "S4RfidBridge",
    [string]$NssmPath = "nssm.exe"
)

$ErrorActionPreference = "Stop"

$nssm = (Get-Command $NssmPath -ErrorAction Stop).Source

if (Get-Service $ServiceName -ErrorAction SilentlyContinue) {
    Stop-Service $ServiceName -ErrorAction SilentlyContinue
    & $nssm remove $ServiceName confirm
}

"Service $ServiceName removed."
