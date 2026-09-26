# Run ONCE as Administrator to install logon task (no UAC every boot).
# Right-click -> Run with PowerShell (Admin), or:
#   powershell -ExecutionPolicy Bypass -File install_autostart.ps1

$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = (Get-Command python).Source
$script = Join-Path $dir "remap_mouse.py"
$taskName = "EncoderMouseRemap"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Host "Re-launching elevated..."
  Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
  exit
}

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Remove Startup shortcut to avoid double-start with the task
$startupLnk = Join-Path ([Environment]::GetFolderPath('Startup')) "EncoderMouseRemap.lnk"
if (Test-Path $startupLnk) {
  Remove-Item $startupLnk -Force
  Write-Host "Removed Startup shortcut (task replaces it)"
}

$action = New-ScheduledTaskAction -Execute $py -Argument "`"$script`"" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
$prin = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest -LogonType Interactive

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $prin -Description "Volume knob -> mouse remapper" -Force | Out-Null
Write-Host "OK: Scheduled task '$taskName' at logon with highest privileges."
Write-Host "Test: Start-ScheduledTask -TaskName $taskName"
pause
