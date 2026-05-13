param(
    [string]$InstallRoot = "C:\s4-log",
    [string]$AppServiceName = "S4toSCP",
    [string]$BridgeServiceName = "S4RfidBridge"
)

$ErrorActionPreference = "Continue"

$appEnv = Join-Path $InstallRoot "S4toSCP\wms-scpapp\backend\.env"
$bridgeSettings = Join-Path $InstallRoot "rfid-bridge\appsettings.json"

"=== Services ==="
Get-Service $AppServiceName, $BridgeServiceName -ErrorAction SilentlyContinue |
    Select-Object Name, Status, StartType

""
"=== Listening ports ==="
netstat -ano | Select-String ":8000|:5000"

""
"=== Backend .env ==="
if (Test-Path $appEnv) {
    Get-Content $appEnv
} else {
    "Missing: $appEnv"
}

""
"=== RFID bridge appsettings.json ==="
if (Test-Path $bridgeSettings) {
    Get-Content $bridgeSettings
} else {
    "Missing: $bridgeSettings"
}

""
"=== Recent logs ==="
Get-ChildItem (Join-Path $InstallRoot "logs") -Filter "*.log" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 10 FullName, Length, LastWriteTime
