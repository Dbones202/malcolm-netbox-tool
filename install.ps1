# Offline PowerShell Installer for NetBox Excel Device Importer
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Installing NetBox Excel Importer (Air-Gapped Offline Mode)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

if (-not (Test-Path "$ScriptDir\wheels")) {
    Write-Host "Error: 'wheels' directory not found in $ScriptDir." -ForegroundColor Red
    Write-Host "Ensure you extracted the complete offline bundle archive." -ForegroundColor Red
    exit 1
}

python -m pip install --no-index --find-links ./wheels .

Write-Host ""
Write-Host "Installation complete!" -ForegroundColor Green
Write-Host "Run 'netbox-excel-importer --help' to get started." -ForegroundColor Green
