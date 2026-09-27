# Nixin PC setup for Windows. Run from the brain\ folder:
#   powershell -ExecutionPolicy Bypass -File ..\scripts\setup-windows.ps1
param([switch]$LocalStt, [switch]$WakeWord, [switch]$NoFirewall)
$ErrorActionPreference = "Stop"
$brain = if (Test-Path "pyproject.toml") { Get-Location } else { Join-Path $PSScriptRoot "..\brain" }
Set-Location $brain

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..." -ForegroundColor Cyan
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

$extras = "voice"
if ($LocalStt) { $extras += ",local-stt" }
if ($WakeWord) { $extras += ",wakeword" }
Write-Host "Creating .venv and installing nixin[$extras]..." -ForegroundColor Cyan
uv venv --python 3.12
uv pip install -e ".[$extras]"

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created .env - put your GROQ_API_KEY in it." -ForegroundColor Yellow }
if (-not (Test-Path "nixin.toml")) { Copy-Item "nixin.example.toml" "nixin.toml"; Write-Host "Created nixin.toml" }

if (-not $NoFirewall) {
    $rule = Get-NetFirewallRule -DisplayName "Nixin link" -ErrorAction SilentlyContinue
    if (-not $rule) {
        Write-Host "Adding firewall rule (TCP 8765, Private networks) - approve the admin prompt..." -ForegroundColor Cyan
        Start-Process powershell -Verb RunAs -Wait -ArgumentList @(
            "-NoProfile", "-Command",
            "New-NetFirewallRule -DisplayName 'Nixin link' -Direction Inbound -Protocol TCP -LocalPort 8765 -Profile Private -Action Allow"
        )
    }
}

Write-Host "`nDone. Next:" -ForegroundColor Green
Write-Host "  notepad .env                 # paste GROQ_API_KEY (free: https://console.groq.com/keys)"
Write-Host "  .venv\Scripts\nixin doctor"
Write-Host "  .venv\Scripts\nixin demo     # try without a phone"
Write-Host "  .venv\Scripts\nixin run      # pair your phone"
