# S4-Log standard Windows install

Standard root:

```text
C:\s4-log
```

Recommended layout:

```text
C:\s4-log\S4toSCP
C:\s4-log\rfid-bridge
C:\s4-log\logs
```

## What to copy to the server

Copy these folders/files to:

```text
C:\s4-log\S4toSCP
```

Required:

```text
S4toSCP\deploy
S4toSCP\wms-scpapp\backend
S4toSCP\wms-app
```

Do not copy generated dependency folders if you want a clean install:

```text
S4toSCP\wms-scpapp\backend\.venv
S4toSCP\wms-app\node_modules
S4toSCP\wms-app\dist
```

The setup script recreates those.

For the RFID bridge, copy the content of the published bridge folder into:

```text
C:\s4-log\rfid-bridge
```

The folder must contain:

```text
RfidBridge.exe
appsettings.json
Utilities\ZebraSdk\Symbol.RFID3.Host.dll
```

You can use the generated ZIP from the build machine:

```text
publish\rfid-bridge-win-x64.zip
```

Extract it directly into `C:\s4-log\rfid-bridge`.

## Backend configuration

Edit:

```text
C:\s4-log\S4toSCP\wms-scpapp\backend\.env
```

Important values:

```env
API_HOST=0.0.0.0
API_PORT=8000
RFID_BRIDGE_URL=http://<bridge-pc-ip>:5000
```

If the bridge runs on the same server:

```env
RFID_BRIDGE_URL=http://127.0.0.1:5000
```

## RFID bridge configuration

Edit:

```text
C:\s4-log\rfid-bridge\appsettings.json
```

Important values:

```json
{
  "RfidBridge": {
    "Provider": "ZebraSdk",
    "Host": "172.16.16.114",
    "Port": 5084,
    "Antennas": [2, 3, 4]
  }
}
```

## Prepare app

Run as Administrator or normal user:

```powershell
cd C:\s4-log\S4toSCP
.\deploy\setup-s4toscp.ps1
```

This creates the Python venv, installs requirements, and builds the frontend.

## Manual tests

Backend and frontend:

```powershell
cd C:\s4-log\S4toSCP
.\deploy\run-s4toscp.ps1
```

Open:

```text
http://<server-ip>:8000
http://<server-ip>:8000/health
```

RFID bridge:

```powershell
cd C:\s4-log\S4toSCP
.\deploy\run-rfid-bridge.ps1
```

Test:

```powershell
Invoke-WebRequest http://127.0.0.1:5000/health -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:5000/rfid/start -Method Post -ContentType "application/json" -Body "{}" -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:5000/rfid/tags -UseBasicParsing
```

## Install services

Install NSSM first and make `nssm.exe` available in PATH, or pass `-NssmPath`.

Run as Administrator:

```powershell
cd C:\s4-log\S4toSCP
.\deploy\install-s4toscp-service.ps1 -OpenFirewall
.\deploy\install-rfid-bridge-service.ps1 -OpenFirewall
```

Services created:

```text
S4toSCP       -> http://0.0.0.0:8000
S4RfidBridge  -> http://0.0.0.0:5000
```

## Check status and variables

```powershell
cd C:\s4-log\S4toSCP
.\deploy\show-s4log-status.ps1
```

Useful commands:

```powershell
Get-Service S4toSCP, S4RfidBridge
nssm dump S4toSCP
nssm dump S4RfidBridge
Get-Content C:\s4-log\S4toSCP\wms-scpapp\backend\.env
Get-Content C:\s4-log\rfid-bridge\appsettings.json
```

Logs:

```text
C:\s4-log\logs\S4toSCP.out.log
C:\s4-log\logs\S4toSCP.err.log
C:\s4-log\logs\S4RfidBridge.out.log
C:\s4-log\logs\S4RfidBridge.err.log
```

## Remove services

```powershell
cd C:\s4-log\S4toSCP
.\deploy\uninstall-s4toscp-service.ps1
.\deploy\uninstall-rfid-bridge-service.ps1
```
