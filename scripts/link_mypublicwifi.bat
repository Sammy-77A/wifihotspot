@echo off
setlocal enabledelayedexpansion
title Link MyPublicWiFi to Cyzora Payment Portal

:: Check for Administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Requesting Administrator privileges to update MyPublicWiFi...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================================
echo   Linking MyPublicWiFi to Cyzora M-Pesa Captive Portal
echo ================================================================
echo.

set "SOURCE_PORTAL=%~dp0..\mypublicwifi_portal.html"
set "TARGET_DIR=C:\Program Files (x86)\MyPublicWiFi\Web"
set "TARGET_FILE=%TARGET_DIR%\login.html"
set "BACKUP_FILE=%TARGET_DIR%\login.html.original"

if not exist "%SOURCE_PORTAL%" (
    echo [ERROR] Source portal template not found at:
    echo "%SOURCE_PORTAL%"
    pause
    exit /b 1
)

if not exist "%TARGET_DIR%" (
    echo [ERROR] MyPublicWiFi Web directory not found at:
    echo "%TARGET_DIR%"
    pause
    exit /b 1
)

:: Backup original if it doesn't already exist
if not exist "%BACKUP_FILE%" (
    echo [INFO] Creating backup of original login.html...
    copy "%TARGET_FILE%" "%BACKUP_FILE%" >nul
    echo [OK] Original saved as login.html.original
) else (
    echo [OK] Backup already exists at login.html.original
)

:: Ensure Windows Firewall allows incoming connections on port 5000
echo [INFO] Configuring Windows Firewall to allow port 5000 for connected phones...
netsh advfirewall firewall delete rule name="WiFi Captive Portal Port 5000" >nul 2>&1
netsh advfirewall firewall add rule name="WiFi Captive Portal Port 5000" dir=in action=allow protocol=TCP localport=5000 profile=any >nul
echo [OK] Firewall rule added for port 5000.

:: Grant write permissions to MyPublicWiFi database
echo [INFO] Granting permissions on MyPublicWiFi database...
if exist "C:\Program Files (x86)\MyPublicWiFi\Data.db" (
    icacls "C:\Program Files (x86)\MyPublicWiFi" /grant "*S-1-5-32-545:(OI)(CI)F" /T >nul 2>&1
    icacls "C:\Program Files (x86)\MyPublicWiFi\Data.db" /grant "*S-1-5-32-545:(F)" >nul 2>&1
    echo [OK] Database and directory permissions configured for session manager.
)

:: Copy custom payment portal
echo [INFO] Installing custom Cyzora M-Pesa portal into MyPublicWiFi...
copy /y "%SOURCE_PORTAL%" "%TARGET_FILE%" >nul
if %errorlevel% equ 0 (
    echo.
    echo ================================================================
    echo   SUCCESS! MyPublicWiFi is now linked to Cyzora M-Pesa Portal!
    echo ================================================================
    echo.
    echo Whenever a customer connects to your hotspot:
    echo 1. They will automatically see the LumoSpeed WiFi payment portal.
    echo 2. Selecting a plan sends an M-Pesa STK Push via Cyzora.
    echo 3. Entering their PIN automatically unlocks full internet access!
    echo.
) else (
    echo [ERROR] Failed to copy custom portal file.
)

echo Press any key to exit...
pause >nul

