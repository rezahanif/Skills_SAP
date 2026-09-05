# Windows PowerShell wrapper for packaging sap2000-mcp (Skills_SAP)
$ErrorActionPreference = 'Stop'
$rootDir = Split-Path -Parent $PSScriptRoot
$aiConnectRoot = $env:AICONNECT_ROOT
if (-not $aiConnectRoot) {
    $cand = Join-Path $rootDir "..\AiConnect"
    if (Test-Path $cand) { $aiConnectRoot = (Resolve-Path $cand).Path }
}

$vendorScript = Join-Path $aiConnectRoot "scripts\release\stage-python-vendor.py"
$packagerScript = Join-Path $aiConnectRoot "scripts\release\package-acpkg.py"

if (-not (Test-Path $packagerScript)) {
    throw "Shared packager not found at '$packagerScript'. Set `$env:AICONNECT_ROOT to AiConnect repo root."
}

# 1. Stage vendor dependencies if missing
$vendorDir = Join-Path $rootDir "_vendor"
if (-not (Test-Path $vendorDir)) {
    Write-Host "== Staging Python dependencies into _vendor/ =="
    python $vendorScript $rootDir
}

# 2. Package .acpkg
Write-Host "== Packaging .acpkg archive =="
python $packagerScript $rootDir @args
