# Windows Auto-Start Installer for WiFi Captive Portal
# Sets up Windows Task Scheduler and Startup shortcut to survive reboots

$ErrorActionPreference = "Stop"

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Installing Auto-Start for WiFi Captive Portal on Windows" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$BatchFile = Join-Path $ScriptDir "start_hotspot.bat"

if (-not (Test-Path $BatchFile)) {
    Write-Error "Launcher script not found at: $BatchFile"
}

# 1. Create Startup Folder Shortcut (User-level startup fallback)
try {
    $StartupFolder = [Environment]::GetFolderPath('Startup')
    $ShortcutPath = Join-Path $StartupFolder "WiFiCaptivePortal.lnk"
    
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $BatchFile
    $Shortcut.WorkingDirectory = $ProjectRoot
    $Shortcut.Description = "Auto-start WiFi Captive Portal with MyPublicWiFi"
    $Shortcut.WindowStyle = 7 # Minimized
    $Shortcut.Save()
    
    Write-Host "[OK] Created Startup shortcut: $ShortcutPath" -ForegroundColor Green
} catch {
    Write-Warning "Could not create Startup shortcut: $_"
}

# 2. Register Windows Scheduled Task (Runs on boot with high privileges)
try {
    $TaskName = "WiFiCaptivePortalService"
    $Action = New-ScheduledTaskAction -Execute $BatchFile -WorkingDirectory $ProjectRoot
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

    # Unregister old task if exists
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    # Register new task
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal | Out-Null
    
    Write-Host "[OK] Registered Scheduled Task: $TaskName (Triggers on Logon with High Privileges)" -ForegroundColor Green
} catch {
    Write-Warning "Could not register Scheduled Task (Run PowerShell as Administrator to enable Scheduled Task): $_"
}

Write-Host ""
Write-Host "Installation Complete! The hotspot stack will automatically start on Windows reboot." -ForegroundColor Yellow

