<#
    setup.ps1 - one-shot dev environment bootstrap for Windows PowerShell.
    Idempotent: safe to re-run. Mirrors the macOS/Linux setup.sh and the README.

    If script execution is blocked, run once in this session:
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#>
$ErrorActionPreference = "Stop"

# Always run from the repo root (directory containing this script).
Set-Location -Path $PSScriptRoot

# Pick a Python launcher.
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    Write-Error "Python not found on PATH. Install Python 3.10+ and retry."
    exit 1
}
Write-Host "==> Using $(& $python --version) at $python"

# 1. Create the virtualenv (reuse if it already exists).
if (-not (Test-Path .venv)) {
    Write-Host "==> Creating virtualenv in .venv"
    & $python -m venv .venv
} else {
    Write-Host "==> Reusing existing .venv"
}

# 2. Activate it.
. .\.venv\Scripts\Activate.ps1

# 3-5. Install dependencies (+ this package in editable mode).
Write-Host "==> Upgrading pip"
python -m pip install --upgrade pip
Write-Host "==> Installing requirements.txt"
pip install -r requirements.txt
Write-Host "==> Installing project (editable)"
pip install -e .

# 6. Install the Chromium browser used by the Playwright uploader.
Write-Host "==> Installing Playwright Chromium"
playwright install chromium

# 7. Seed a local settings.yaml from the example (never overwrite an existing one).
if (-not (Test-Path config/settings.yaml)) {
    Write-Host "==> Creating config/settings.yaml from config/settings.example.yaml"
    Copy-Item config/settings.example.yaml config/settings.yaml
} else {
    Write-Host "==> config/settings.yaml already exists - left untouched"
}

Write-Host ""
Write-Host "Setup complete. Activate the environment with:"
Write-Host "    .\.venv\Scripts\Activate.ps1"
