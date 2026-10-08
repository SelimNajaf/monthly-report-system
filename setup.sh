#!/usr/bin/env bash
#
# setup.sh — one-shot dev environment bootstrap for macOS / Linux.
# Idempotent: safe to re-run. Mirrors the Windows setup.ps1 and the README.
#
set -euo pipefail

# Always run from the repo root (directory containing this script).
cd "$(dirname "$0")"

# Prefer python3, fall back to python.
PYTHON="$(command -v python3 || command -v python || true)"
if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3 not found on PATH. Install Python 3.10+ and retry." >&2
    exit 1
fi

echo "==> Using $($PYTHON --version) at $PYTHON"

# 1. Create the virtualenv (reuse if it already exists).
if [ ! -d .venv ]; then
    echo "==> Creating virtualenv in .venv"
    "$PYTHON" -m venv .venv
else
    echo "==> Reusing existing .venv"
fi

# 2. Activate it.
# shellcheck disable=SC1091
source .venv/bin/activate

# 3-5. Install dependencies (+ this package in editable mode).
echo "==> Upgrading pip"
pip install --upgrade pip
echo "==> Installing requirements.txt"
pip install -r requirements.txt
echo "==> Installing project (editable)"
pip install -e .

# 6. Install the Chromium browser used by the Playwright uploader.
echo "==> Installing Playwright Chromium"
playwright install chromium

# 7. Seed a local settings.yaml from the example (never overwrite an existing one).
if [ ! -f config/settings.yaml ]; then
    echo "==> Creating config/settings.yaml from config/settings.example.yaml"
    cp config/settings.example.yaml config/settings.yaml
else
    echo "==> config/settings.yaml already exists — left untouched"
fi

echo
echo "Setup complete. Activate the environment with:"
echo "    source .venv/bin/activate"
