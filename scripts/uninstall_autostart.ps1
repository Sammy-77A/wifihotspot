# Windows Auto-Start Uninstaller for WiFi Captive Portal

Write-Host "Removing auto-start configuration..." -ForegroundColor Cyan

$TaskName = "WiFiCaptivePortalService"
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "[OK] Removed Scheduled Task: $TaskName" -ForegroundColor Green
} catch {
    Write-Warning "Scheduled task was not found or could not be removed."
}

try {
    $StartupFolder = [Environment]::GetFolderPath('Startup')
    $ShortcutPath = Join-Path $StartupFolder "WiFiCaptivePortal.lnk"
    if (Test-Path $ShortcutPath) {
        Remove-Item -Path $ShortcutPath -Force
        Write-Host "[OK] Removed Startup shortcut: $ShortcutPath" -ForegroundColor Green
    }
} catch {
    Write-Warning "Startup shortcut could not be removed: $_"
}

Write-Host "Uninstallation complete." -ForegroundColor Yellow

