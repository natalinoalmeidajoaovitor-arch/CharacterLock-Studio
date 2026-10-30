@echo off
setlocal
title CharacterLock Studio
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open-studio.ps1"
if errorlevel 1 (
    echo.
    echo Nao foi possivel abrir o Studio. Veja a mensagem acima.
    pause
)
endlocal
