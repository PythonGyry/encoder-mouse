# Stop encoder-mouse remapper (works for elevated instances via PID file)
$ErrorActionPreference = "SilentlyContinue"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $dir "remap.pid"

if (Test-Path $pidFile) {
  $procId = (Get-Content $pidFile -Raw).Trim()
  if ($procId -match '^\d+$') {
    Write-Host "Stopping PID $procId (from remap.pid)"
    Stop-Process -Id ([int]$procId) -Force
  }
  Remove-Item $pidFile -Force
}

Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match 'encoder-mouse\\remap_mouse\.py|remap_mouse\.py') } |
  ForEach-Object {
    Write-Host "Stopping PID $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force
  }

Write-Host "done"
