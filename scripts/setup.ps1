$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.11+ was not found on PATH. Install Python 3.11+ or use CharacterLockStudio.exe from GitHub Releases."
}

if (-not (Test-Path "$root\.venv\Scripts\python.exe")) {
    Write-Host "[1/3] Creating local Python virtual environment (.venv)..."
    python -m venv "$root\.venv"
}

Write-Host "[2/3] Installing backend and Comfy SDK dependencies..."
& "$root\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$root\.venv\Scripts\python.exe" -m pip install -r "$root\backend\requirements.txt"

if (Get-Command pnpm -ErrorAction SilentlyContinue) {
    Write-Host "[3/3] Installing and building React frontend with pnpm..."
    Push-Location "$root\frontend"
    try {
        pnpm install --frozen-lockfile
        pnpm build
    } finally {
        Pop-Location
    }
} elseif (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Host "[3/3] Installing and building React frontend with npm..."
    Push-Location "$root\frontend"
    try {
        npm install
        npm run build
    } finally {
        Pop-Location
    }
} else {
    Write-Host "[3/3] Node.js/pnpm not detected; skipping frontend build (install Node.js 20+ for source builds, or use CharacterLockStudio.exe)."
}

Write-Host ""
Write-Host "Setup complete! Next steps:"
Write-Host "  1. Check/download models : .\.venv\Scripts\python.exe scripts\model_setup.py --check-only"
Write-Host "  2. Launch Studio         : .\scripts\open-studio.ps1"
