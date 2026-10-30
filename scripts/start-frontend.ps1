$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\frontend"

if (Get-Command pnpm -ErrorAction SilentlyContinue) {
    pnpm dev --host 127.0.0.1 --port 5173
} elseif (Get-Command npm -ErrorAction SilentlyContinue) {
    npm run dev -- --host 127.0.0.1 --port 5173
} else {
    throw "Neither pnpm nor npm was found on PATH. Install Node.js 20+ or launch prebuilt Studio via launcher_main.py / CharacterLockStudio.exe."
}
