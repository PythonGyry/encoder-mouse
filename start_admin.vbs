' Restart remapper as Administrator (fixes WireGuard / elevated apps)
Option Explicit
Dim sh, dir, py, script, stopCmd
Set sh = CreateObject("Shell.Application")
dir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
py = "python"
script = """" & dir & "\remap_mouse.py" & """"
stopCmd = "-NoProfile -ExecutionPolicy Bypass -File """ & dir & "\stop.ps1"""
' Stop must also be elevated to kill previous admin instance
sh.ShellExecute "powershell", stopCmd, dir, "runas", 0
WScript.Sleep 1200
sh.ShellExecute py, script, dir, "runas", 1
