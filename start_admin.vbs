' Restart remapper as Administrator (fixes WireGuard / elevated apps)
Option Explicit
Dim sh, dir, py, script
Set sh = CreateObject("Shell.Application")
dir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
py = "python"
script = """" & dir & "\remap_mouse.py" & """"
' Stop old non-elevated instances
CreateObject("WScript.Shell").Run "powershell -NoProfile -ExecutionPolicy Bypass -File """ & dir & "\stop.ps1""", 0, True
WScript.Sleep 400
sh.ShellExecute py, script, dir, "runas", 1
