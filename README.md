# encoder-mouse

Remap a keyboard volume knob (encoder) to mouse movement on Windows.

Tested with Bluetooth keyboards that send `Volume Up` / `Volume Down` / `Volume Mute` (e.g. HATOR Icefall 75P).

## Controls

| Action | Result |
|--------|--------|
| Turn knob | Move mouse **X** |
| **Ctrl** + turn | Move mouse **Y** |
| **Delete** + turn | Mouse **wheel** scroll |
| Click knob (Mute) | Toggle remap ON/OFF (OFF = normal volume) |
| **Ctrl** + **Delete** | Left click (without Ctrl chord) |
| **Ctrl** + **Page Up** | Right click (without Ctrl chord) |
| **Ctrl** + **Alt** + **Q** | Quit |

## Requirements

- Windows 10/11
- [Python 3](https://www.python.org/downloads/) with **Add to PATH**

## Run

**Recommended** (works over elevated apps like WireGuard):

```bat
start_admin.vbs
```

Accept the UAC prompt.

Or without elevation:

```bat
python remap_mouse.py
```

Stop:

```bat
powershell -File stop.ps1
```

## Autostart

1. `Win+R` → `shell:startup`
2. Shortcut to `start_admin.vbs`

Or Task Scheduler → run `wscript.exe` with full path to `start_admin.vbs`, enable **Run with highest privileges**.

## Notes

- Must run **as Administrator** if the focused app is elevated (VPN clients, some installers).
- Only a keyboard low-level hook is used (no mouse hook), so a crash should not freeze the mouse.
- Knob click toggles remap; a short Delete tap still sends Delete if you did not scroll with it.

## License

MIT
