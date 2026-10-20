# Build HorillaAgent.exe
# Run this script from the horilla-agent/ directory on a Windows machine.
#
#   cd horilla-agent
#   .\build.ps1
#
# Output: dist\HorillaAgent.exe

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> Installing / upgrading dependencies..." -ForegroundColor Cyan
python -m pip install -q -r requirements.txt

Write-Host "==> Generating placeholder icon (replace assets\horilla_agent.ico with your real icon)..." -ForegroundColor Cyan
# If PIL is available and no real icon exists, create a placeholder
python -c "
from pathlib import Path
ico = Path('assets/horilla_agent.ico')
if not ico.exists():
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGBA', (64, 64), (1, 115, 145, 255))
        d = ImageDraw.Draw(img)
        d.ellipse([16,16,48,48], fill=(255,255,255,200))
        img.save(str(ico), format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64)])
        print('Placeholder icon created.')
    except Exception as e:
        print(f'Could not create icon ({e}); place assets/horilla_agent.ico manually.')
else:
    print('Icon already exists.')
"

Write-Host "==> Building HorillaAgent.exe with PyInstaller..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm HorillaAgent.spec

Write-Host ""
Write-Host "==> Build complete!" -ForegroundColor Green
Write-Host "    Executable : $PSScriptRoot\dist\HorillaAgent.exe"
$hash = (Get-FileHash "$PSScriptRoot\dist\HorillaAgent.exe" -Algorithm SHA256).Hash
Write-Host "    SHA-256     : $hash"
