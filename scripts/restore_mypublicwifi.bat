@echo off
setlocal enabledelayedexpansion
title Restore Original MyPublicWiFi Portal

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Requesting Administrator privileges to restore MyPublicWiFi...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

set "TARGET_DIR=C:\Program Files (x86)\MyPublicWiFi\Web"
set "TARGET_FILE=%TARGET_DIR%\login.html"
set "BACKUP_FILE=%TARGET_DIR%\login.html.original"

if exist "%BACKUP_FILE%" (
    copy /y "%BACKUP_FILE%" "%TARGET_FILE%" >nul
    echo [OK] Original MyPublicWiFi login.html restored successfully.
) else (
    echo [ERROR] Backup file not found at: %BACKUP_FILE%
)

echo Press any key to exit...
pause >nul

