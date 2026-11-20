@echo off
title WiFi Captive Portal - Shutdown Controller
echo ================================================================
echo   Stopping WiFi Captive Portal Services
echo ================================================================

echo [INFO] Stopping Python Flask captive portal processes...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :5000 ^| findstr LISTENING') do (
    echo Terminating PID: %%a listening on port 5000...
    taskkill /F /PID %%a >nul 2>&1
)

echo [OK] Captive portal backend stopped.

set /p killGate="Do you also want to stop MyPublicWiFi? (y/N): "
if /i "%killGate%"=="y" (
    taskkill /F /IM MyPublicWiFi.exe >nul 2>&1
    echo [OK] MyPublicWiFi stopped.
)

echo.
echo Shutdown complete.
pause

