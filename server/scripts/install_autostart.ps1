<#
.SYNOPSIS
    Register (or remove) the scheduled task that starts Ratchet at login.

.DESCRIPTION
    Creates a per-user "At log on" task running Ratchet.vbs, which launches the
    tray app with no console window. Task Scheduler is used rather than the
    Startup folder because only it can delay the start: at login Tailscale may
    still be coming up, and Ratchet needs a tailnet address to bind to. (The
    tray app also waits for one by itself, so the delay is belt-and-braces.)

    The task runs only while you are logged on — a tray icon needs a desktop
    session — and needs no administrator rights.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
    powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1 -DelayMinutes 2
    powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1 -Remove
#>
param(
    [int]$DelayMinutes = 1,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$taskName = "Ratchet"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Removed the '$taskName' task; Ratchet will no longer start at login."
    } else {
        Write-Host "No '$taskName' task is registered."
    }
    return
}

# scripts\ -> server\ -> repo root
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$launcher = Join-Path $repoRoot "Ratchet.vbs"
if (-not (Test-Path $launcher)) {
    throw "Launcher not found at $launcher"
}

$action = New-ScheduledTaskAction -Execute "wscript.exe" `
    -Argument ("`"" + $launcher + "`"") -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT${DelayMinutes}M"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description ("Start Ratchet in the notification area " +
    "at login (delayed $DelayMinutes minute(s) so Tailscale is up).") -Force | Out-Null

Write-Host "Registered '$taskName': runs $launcher at login, $DelayMinutes minute(s) after."
Write-Host "Remove it again with:  ... install_autostart.ps1 -Remove"
