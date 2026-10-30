@echo off
setlocal
chcp 65001 >nul
title CharacterLock Model Setup
cd /d "%~dp0"
if exist "%~dp0CharacterLockStudio.exe" (
    "%~dp0CharacterLockStudio.exe" --setup-models %*
) else if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0scripts\model_setup.py" %*
) else (
    python "%~dp0scripts\model_setup.py" %*
)
echo.
pause
endlocal
