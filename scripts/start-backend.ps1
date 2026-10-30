$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) { throw "Execute scripts\setup.ps1 primeiro." }
Push-Location (Join-Path $projectDir "backend")
try {
    & $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
    if ($LASTEXITCODE -ne 0) { throw "O backend encerrou com erro." }
} finally { Pop-Location }

