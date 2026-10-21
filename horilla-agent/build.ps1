# Build InfisetuAgent.exe
# Run this script from the horilla-agent/ directory on a Windows machine.
#
#   cd horilla-agent
#   .\build.ps1
#
# Output: dist\InfisetuAgent.exe

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> Installing / upgrading dependencies..." -ForegroundColor Cyan
python -m pip install -q -r requirements.txt

Write-Host "==> Checking assets..." -ForegroundColor Cyan
python -c "
from pathlib import Path
ico = Path('assets/infisetu_agent.ico')
if ico.exists():
    print('Icon found:', ico)
else:
    print('WARNING: assets/infisetu_agent.ico not found — place it before building.')
"

Write-Host "==> Building InfisetuAgent.exe with PyInstaller..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm InfisetuAgent.spec

Write-Host ""
Write-Host "==> Build complete!" -ForegroundColor Green
Write-Host "    Executable : $PSScriptRoot\dist\InfisetuAgent.exe"
$hash = (Get-FileHash "$PSScriptRoot\dist\InfisetuAgent.exe" -Algorithm SHA256).Hash
Write-Host "    SHA-256     : $hash"
