@echo off
setlocal enabledelayedexpansion
title WiFi Captive Portal - Master Launcher

:: Check for Administrator privileges and self-elevate
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Requesting Administrator privileges to manage hotspot and firewall...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: Ensure MyPublicWiFi directory and database have full write access for Python
if exist "C:\Program Files (x86)\MyPublicWiFi\Data.db" (
    icacls "C:\Program Files (x86)\MyPublicWiFi" /grant "*S-1-5-32-545:(OI)(CI)F" /T >nul 2>&1
    icacls "C:\Program Files (x86)\MyPublicWiFi\Data.db" /grant "*S-1-5-32-545:(F)" >nul 2>&1
)

:: Clean up any obsolete WiFiPortal block firewall rules and AutoLogins
python "%~dp0cleanup_firewall.py" >nul 2>&1

echo ================================================================
echo   WiFi Captive Portal with Cyzora M-Pesa and MyPublicWiFi
echo ================================================================

cd /d "%~dp0\.."

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not found in PATH!
    echo Please install Python 3.10+ and check 'Add Python to PATH'.
    pause
    exit /b 1
)

:: 2. Check and start MyPublicWiFi if configured
tasklist /fi "imagename eq MyPublicWiFi.exe" 2>NUL | find /i "MyPublicWiFi.exe" >nul
if %errorlevel% neq 0 (
    if exist "C:\Program Files (x86)\MyPublicWiFi\MyPublicWiFi.exe" (
        echo [INFO] Starting MyPublicWiFi Hotspot...
        start "" "C:\Program Files (x86)\MyPublicWiFi\MyPublicWiFi.exe"
    ) else if exist "C:\Program Files\MyPublicWiFi\MyPublicWiFi.exe" (
        echo [INFO] Starting MyPublicWiFi Hotspot...
        start "" "C:\Program Files\MyPublicWiFi\MyPublicWiFi.exe"
    ) else (
        echo [NOTICE] MyPublicWiFi executable not found at default path. Ensure it is started manually.
    )
) else (
    echo [OK] MyPublicWiFi is already running.
)

:: 3. Start Python Flask Backend with Auto-Restart Loop
echo.
echo [INFO] Starting Captive Portal Backend and Session Expiry Worker...
echo [INFO] Running on http://0.0.0.0:5000 (Local test: http://127.0.0.1:5000)
echo.

:run_server
python app.py
echo.
echo [WARNING] Flask server process stopped unexpectedly at %date% %time%!
echo [INFO] Auto-restarting in 3 seconds... (Press Ctrl+C to stop)
timeout /t 3 /nobreak >nul
goto run_server

