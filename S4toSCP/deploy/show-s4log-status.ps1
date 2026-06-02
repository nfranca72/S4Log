param(
    [string]$InstallRoot = "C:\s4-log",
    [string]$AppServiceName = "S4toSCP",
    [string[]]$BridgeServiceNames = @("S4RfidBridgeTunnel1", "S4RfidBridgeTunnel2", "S4RfidBridge"),
    [int[]]$BridgePorts = @(5001, 5002, 5000),
    [string]$AppUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Continue"

$appEnv = Join-Path $InstallRoot "S4toSCP\wms-scpapp\backend\.env"
$bridgeSettings = Join-Path $InstallRoot "rfid-bridge\appsettings.json"

"=== Services ==="
$serviceNames = @($AppServiceName) + $BridgeServiceNames
Get-Service $serviceNames -ErrorAction SilentlyContinue |
    Select-Object Name, Status, StartType

""
"=== Service commands ==="
Get-CimInstance Win32_Service |
    Where-Object { $serviceNames -contains $_.Name } |
    Select-Object Name, State, StartMode, ProcessId, PathName |
    Format-List

""
"=== Listening ports ==="
$ports = @(8000) + $BridgePorts
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $ports -contains $_.LocalPort } |
    Select-Object LocalAddress, LocalPort, OwningProcess, State |
    Sort-Object LocalPort |
    Format-Table -AutoSize

""
"=== Bridge health ==="
foreach ($port in $BridgePorts) {
    $url = "http://127.0.0.1:$port/health"
    try {
        $response = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 3
        "$url -> $($response.StatusCode) $($response.Content)"
    } catch {
        "$url -> FAIL $($_.Exception.Message)"
    }
}

""
"=== Configured tunnel URLs ==="
if (Test-Path $appEnv) {
    Get-Content $appEnv | Select-String -Pattern "RFID_BRIDGE|RFID_HOST|RFID_PORT"
} else {
    "Missing: $appEnv"
}

""
"=== Tunnels from API/DB ==="
try {
    $response = Invoke-WebRequest "$AppUrl/api/config/tunnels" -UseBasicParsing -TimeoutSec 5
    $response.Content | ConvertFrom-Json |
        Select-Object tunnel_id, tunnel_code, tunnel_desc, host, port, @{Name="antennas";Expression={$_.antennas -join ","}}, active |
        Format-Table -AutoSize
} catch {
    "$AppUrl/api/config/tunnels -> FAIL $($_.Exception.Message)"
}

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
