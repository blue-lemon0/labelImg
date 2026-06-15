# build_win7.ps1 — Build labelImg.exe for Windows 7
#
# Uses Python 3.8 (Python 3.9+ official builds depend on Win8+ API
# api-ms-win-core-path-l1-1-0.dll, so we must use 3.8).
# Only needed if you must run on Win7. Requires Python 3.8.x installed.
#
# Usage:
#   .\build_win7.ps1
#
# Output: dist_win7\labelImg_win7.exe

$ErrorActionPreference = 'Stop'

$venv_dir = Join-Path $PSScriptRoot 'venv-py38'
$py38_path = "$env:LOCALAPPDATA\Programs\Python38\python.exe"

# ── Ensure Python 3.8 installed ──
if (-not (Test-Path $py38_path)) {
    Write-Host "Python 3.8 not found at $py38_path"
    Write-Host "Download from: https://www.python.org/downloads/release/python-3810/"
    Write-Host "Install to: $env:LOCALAPPDATA\Programs\Python38"
    exit 1
}

# ── Create venv if not exists ──
if (-not (Test-Path "$venv_dir\Scripts\python.exe")) {
    Write-Host "Creating Python 3.8 venv ..."
    & $py38_path -m venv $venv_dir
    & "$venv_dir\Scripts\python.exe" -m pip install --upgrade pip -q
}

# ── Install dependencies ──
Write-Host "Installing dependencies ..."
& "$venv_dir\Scripts\pip.exe" install --default-timeout=120 pyqt5 lxml pyinstaller pillow -q

# ── Build ──
Write-Host "Building labelImg_win7.exe ..."
& "$venv_dir\Scripts\pyinstaller.exe" labelImg.spec --distpath dist_win7 --workpath build_win7 -y

# ── Rename to indicate Win7 target ──
if (Test-Path "dist_win7\labelImg.exe") {
    Move-Item -Force "dist_win7\labelImg.exe" "dist_win7\labelImg_win7.exe"
    Write-Host "Done → dist_win7\labelImg_win7.exe"
} else {
    Write-Host "ERROR: Build failed" -ForegroundColor Red
    exit 1
}
