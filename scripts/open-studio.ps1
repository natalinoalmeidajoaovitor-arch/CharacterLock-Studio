$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (Test-Path "$root\CharacterLockStudio.exe") {
    & "$root\CharacterLockStudio.exe" @args
    exit $LASTEXITCODE
}

$python = "$root\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python "$root\launcher_main.py" @args
