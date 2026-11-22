@echo off
setlocal enabledelayedexpansion
title Hotspot DHCP & IP Configuration Repair

:: 1. Self-elevate to Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Requesting Administrator privileges to repair network adapter...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ================================================================
echo   Hotspot DHCP & IP Configuration Repair Tool
echo ================================================================
echo.

:: 2. Stop conflicting processes & services
echo [1/5] Stopping MyPublicWiFi and Windows Sharing services...
taskkill /F /IM MyPublicWiFi.exe >nul 2>&1
net stop SharedAccess >nul 2>&1

:: 3. Clear conflicting dual-IP registry binding on Wi-Fi Direct virtual adapter
echo [2/5] Cleaning up conflicting IP addresses (192.168.5.1 and 192.168.137.1)...
powershell -NoProfile -Command ^
    "$key = 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\{2662A9E2-CA06-4444-BA0B-7CC488D11DEB}'; " ^
    "if (Test-Path $key) { " ^
    "    Set-ItemProperty -Path $key -Name 'IPAddress' -Value @('0.0.0.0'); " ^
    "    Set-ItemProperty -Path $key -Name 'SubnetMask' -Value @('0.0.0.0'); " ^
    "    Set-ItemProperty -Path $key -Name 'EnableDHCP' -Value 1; " ^
    "    Write-Host '  [OK] Reset registry TCP/IP parameters for Wi-Fi Direct adapter.' -ForegroundColor Green; " ^
    "} else { " ^
    "    Write-Host '  [INFO] Registry key not found, checking all interfaces...' -ForegroundColor Yellow; " ^
    "}"

:: 4. Reset adapter IP settings to dynamic DHCP
echo [3/5] Resetting Wi-Fi Direct adapter to DHCP...
powershell -NoProfile -Command ^
    "Get-NetAdapter -IncludeHidden | Where-Object { $_.InterfaceDescription -match 'Wi-Fi Direct' } | ForEach-Object { " ^
    "    $alias = $_.Name; " ^
    "    Write-Host ('  Processing adapter: ' + $alias); " ^
    "    Remove-NetIPAddress -InterfaceAlias $alias -Confirm:$false -ErrorAction SilentlyContinue; " ^
    "    Set-NetIPInterface -InterfaceAlias $alias -Dhcp Enabled -ErrorAction SilentlyContinue; " ^
    "}"

:: 5. Flush ARP table & DNS cache
echo [4/5] Flushing ARP table and network cache...
arp -d * >nul 2>&1
ipconfig /flushdns >nul 2>&1

:: 6. Restart Windows Internet Connection Sharing (SharedAccess) service
echo [5/5] Restarting Windows Hotspot DHCP service (SharedAccess)...
net start SharedAccess >nul 2>&1

echo.
echo ================================================================
echo   [SUCCESS] Network repair complete!
echo ================================================================
echo.
echo Conflicting dual-IP bindings have been removed.
echo.
echo How to connect now:
echo   - If using WINDOWS MOBILE HOTSPOT:
echo       1. Make sure MyPublicWiFi is NOT running.
echo       2. Toggle Windows Mobile Hotspot OFF and back ON in Windows Settings.
echo       3. Reconnect your phone.
echo.
echo   - If using MYPUBLICWIFI with LUMOSPEED:
echo       1. Make sure Windows Mobile Hotspot is turned OFF in Windows Settings.
echo       2. Run scripts\start_hotspot.bat (it will automatically launch MyPublicWiFi).
echo       3. Reconnect your phone.
echo.
echo Press any key to exit...
pause >nul
