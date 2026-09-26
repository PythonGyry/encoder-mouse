@echo off
:: Run encoder->mouse remapper elevated (needed for WireGuard and other admin apps)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process -FilePath 'python' -ArgumentList '\"%~dp0remap_mouse.py\"' -Verb RunAs -WorkingDirectory '%~dp0'"
