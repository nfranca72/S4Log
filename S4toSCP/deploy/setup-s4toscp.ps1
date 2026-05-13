param(
    [string]$InstallRoot = "C:\s4-log",
    [string]$AppRoot = (Join-Path $InstallRoot "S4toSCP"),
    [string]$Python = "python",
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"

$backendDir = Join-Path $AppRoot "wms-scpapp\backend"
$frontendDir = Join-Path $AppRoot "wms-app"
$logsDir = Join-Path $InstallRoot "logs"
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @Arguments 2>&1 | ForEach-Object { Write-Host $_ }
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Get-PythonVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $version = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to execute Python at $PythonPath. Output: $version"
        }

        return [string]$version
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Assert-SupportedPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath
    )

    $version = Get-PythonVersion $PythonPath
    if ($version -notmatch "^(3\.11|3\.12)\.") {
        throw "Unsupported Python version $version at $PythonPath. Install Python 3.12 x64 and rerun this script. If .venv already exists, delete wms-scpapp\backend\.venv first."
    }
}

New-Item -ItemType Directory -Force $logsDir | Out-Null

if (-not (Test-Path $venvPython)) {
    Assert-SupportedPython $Python

    Push-Location $backendDir
    try {
        Invoke-Native $Python -m venv .venv
    }
    finally {
        Pop-Location
    }
}
else {
    Assert-SupportedPython $venvPython
}

Push-Location $backendDir
try {
    $env:PIP_NO_CACHE_DIR = "1"
    Invoke-Native $venvPython -m pip install --no-cache-dir --upgrade pip
    Invoke-Native $venvPython -m pip install --no-cache-dir -r requirements.txt
}
finally {
    Remove-Item Env:\PIP_NO_CACHE_DIR -ErrorAction SilentlyContinue
    Pop-Location
}

if (-not $SkipFrontendBuild) {
    Push-Location $frontendDir
    try {
        Invoke-Native "npm" ci
        Invoke-Native "npm" run build
    }
    finally {
        Pop-Location
    }
}

"S4toSCP setup completed."
