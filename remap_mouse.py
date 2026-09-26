"""
Icefall encoder -> smooth mouse move + key remaps.

Turn              -> mouse X
Ctrl + turn       -> mouse Y
Delete + turn     -> mouse wheel scroll
Click encoder     -> toggle mouse remap ON/OFF (OFF = normal volume)
Ctrl + Page Up    -> right click
Ctrl + Delete     -> left click
Delete tap        -> normal Delete (if not used for scroll)

Emergency quit: Ctrl+Alt+Q
"""
from __future__ import annotations

import atexit
import ctypes
import ctypes.wintypes as w
import math
import os
import sys
import threading
import time
from pathlib import Path

# --- feel ---
DIR_SIGN_X = 1
DIR_SIGN_Y = 1
DIR_SIGN_SCROLL = 1  # +VOLUME_UP => scroll up
BASE_IMPULSE = 2.2
SPEED_GAIN = 0.55
SPEED_EXP = 1.15
MIN_IMPULSE = 1.5
MAX_IMPULSE = 28.0
FRICTION = 6.5
MAX_SPEED = 1400.0
TICK_HZ = 180
DEDUPE_MS = 12
WHEEL_DELTA = 120

LOG = Path(__file__).with_name("remap.log")
PID_FILE = Path(__file__).with_name("remap.pid")
MUTEX_NAME = "Global\\PythonGyryEncoderMouseRemap"

user32 = ctypes.WinDLL("user32", use_last_error=True)

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
HC_ACTION = 0
LLKHF_INJECTED = 0x10
VK_VOLUME_MUTE, VK_VOLUME_DOWN, VK_VOLUME_UP = 0xAD, 0xAE, 0xAF
VK_CONTROL, VK_LCONTROL, VK_RCONTROL = 0x11, 0xA2, 0xA3
VK_MENU, VK_Q = 0x12, 0x51
VK_PRIOR, VK_DELETE = 0x21, 0x2E  # Page Up / Delete
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP = 0x0002

ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32
LONG_PTR = ctypes.c_int64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_int32
LRESULT, WPARAM, LPARAM, HHOOK = LONG_PTR, ULONG_PTR, LONG_PTR, ctypes.c_void_p


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", w.DWORD),
        ("scanCode", w.DWORD),
        ("flags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", w.LONG),
        ("dy", w.LONG),
        ("mouseData", w.DWORD),
        ("dwFlags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", w.DWORD), ("u", _U)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, w.HINSTANCE, w.DWORD]
user32.SetWindowsHookExW.restype = HHOOK
user32.CallNextHookEx.argtypes = [HHOOK, ctypes.c_int, WPARAM, LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [HHOOK]
user32.UnhookWindowsHookEx.restype = w.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.SendInput.argtypes = [w.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = w.UINT
user32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
user32.GetMessageW.restype = w.BOOL
user32.PostThreadMessageW.argtypes = [w.DWORD, w.UINT, WPARAM, LPARAM]
user32.PostThreadMessageW.restype = w.BOOL

WM_QUIT = 0x0012

_h_kb = HHOOK()
_cb_ref = None
_thread_id = 0
_stop = threading.Event()

_lock = threading.Lock()
_vel_x = 0.0
_vel_y = 0.0
_acc_x = 0.0
_acc_y = 0.0
_last_tick_t = 0.0
_last_vk = 0
_last_vk_t = 0.0
_mouse_on = True
_mute_held = False  # edge-trigger: one toggle per physical press
_delete_held = False
_delete_used_as_mod = False
_mutex = None


def log(msg: str) -> None:
    line = time.strftime("%H:%M:%S") + f"  {msg}"
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


def set_mouse_on(on: bool) -> None:
    global _mouse_on, _vel_x, _vel_y, _acc_x, _acc_y, _delete_held, _delete_used_as_mod
    if _mouse_on == on:
        return
    _mouse_on = on
    if not on:
        _vel_x = _vel_y = _acc_x = _acc_y = 0.0
        _delete_held = False
        _delete_used_as_mod = False
    log(f"mouse remap {'ON' if on else 'OFF (volume + normal keys)'}")
    # Audible feedback so toggle is obvious
    try:
        user32.MessageBeep(0x00000040 if on else 0x00000010)
    except Exception:
        pass


def ensure_single_instance() -> bool:
    """Kill previous instance (via pid file), then take a mutex."""
    global _mutex
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
    kernel32.CreateMutexW.restype = ctypes.c_void_p

    if PID_FILE.exists():
        try:
            old = int(PID_FILE.read_text(encoding="utf-8").strip())
            if old and old != os.getpid():
                try:
                    os.kill(old, 9)
                    log(f"killed previous instance pid={old}")
                    time.sleep(0.3)
                except OSError:
                    pass
        except ValueError:
            pass

    _mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    already = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    if already:
        log("another instance still holds mutex — exit")
        return False
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def ctrl_held() -> bool:
    return bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)


def delete_held() -> bool:
    return _delete_held or bool(user32.GetAsyncKeyState(VK_DELETE) & 0x8000)


def mouse_event(flags: int, data: int = 0) -> None:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    # mouseData as unsigned 32-bit (negative wheel via wrap)
    md = ctypes.c_uint32(data).value if data < 0 else data
    inp.mi = MOUSEINPUT(0, 0, md, flags, 0, 0)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def move_rel(dx: int, dy: int) -> None:
    if dx == 0 and dy == 0:
        return
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE, 0, 0)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def click_left() -> None:
    _click_without_ctrl(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)


def click_right() -> None:
    _click_without_ctrl(MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)


def _click_without_ctrl(down_flag: int, up_flag: int) -> None:
    """Click without Ctrl chord (apps would otherwise see Ctrl+click)."""
    left = bool(user32.GetAsyncKeyState(VK_LCONTROL) & 0x8000)
    right = bool(user32.GetAsyncKeyState(VK_RCONTROL) & 0x8000)
    if left:
        user32.keybd_event(VK_LCONTROL, 0, KEYEVENTF_KEYUP, 0)
    if right:
        user32.keybd_event(VK_RCONTROL, 0, KEYEVENTF_KEYUP, 0)
    mouse_event(down_flag)
    mouse_event(up_flag)
    if left:
        user32.keybd_event(VK_LCONTROL, 0, 0, 0)
    if right:
        user32.keybd_event(VK_RCONTROL, 0, 0, 0)


def scroll_wheel(direction: int, notches: int = 1) -> None:
    """direction +1 = up, -1 = down."""
    delta = WHEEL_DELTA * notches * direction * DIR_SIGN_SCROLL
    mouse_event(MOUSEEVENTF_WHEEL, delta)


def tap_delete() -> None:
    """Inject a real Delete (hook lets injected keys through)."""
    user32.keybd_event(VK_DELETE, 0, 0, 0)
    user32.keybd_event(VK_DELETE, 0, KEYEVENTF_KEYUP, 0)


def impulse_for_dt(dt: float) -> float:
    dt = max(dt, 0.008)
    rate = 1.0 / dt
    raw = BASE_IMPULSE + SPEED_GAIN * (rate**SPEED_EXP)
    return float(min(MAX_IMPULSE, max(MIN_IMPULSE, raw)))


def on_tick(direction: int) -> None:
    global _vel_x, _vel_y, _last_tick_t, _delete_used_as_mod
    now = time.perf_counter()
    if not _mouse_on:
        return

    # Delete held -> scroll (priority over Ctrl+Y)
    if delete_held():
        _delete_used_as_mod = True
        dt = now - _last_tick_t if _last_tick_t else 0.12
        _last_tick_t = now
        # faster spin => more notches (1..3)
        notches = 1
        if dt < 0.04:
            notches = 3
        elif dt < 0.08:
            notches = 2
        scroll_wheel(direction, notches)
        return

    with _lock:
        dt = now - _last_tick_t if _last_tick_t else 0.12
        _last_tick_t = now
        imp = impulse_for_dt(dt) * 55.0
        if ctrl_held():
            _vel_y += direction * DIR_SIGN_Y * imp
            _vel_y = max(-MAX_SPEED, min(MAX_SPEED, _vel_y))
        else:
            _vel_x += direction * DIR_SIGN_X * imp
            _vel_x = max(-MAX_SPEED, min(MAX_SPEED, _vel_x))


def motion_loop() -> None:
    global _vel_x, _vel_y, _acc_x, _acc_y
    last = time.perf_counter()
    while not _stop.is_set():
        time.sleep(1.0 / TICK_HZ)
        now = time.perf_counter()
        dt = now - last
        last = now
        with _lock:
            if not _mouse_on:
                _vel_x = _vel_y = _acc_x = _acc_y = 0.0
                continue
            decay = math.exp(-FRICTION * dt)
            _vel_x *= decay
            _vel_y *= decay
            if abs(_vel_x) < 0.5:
                _vel_x = 0.0
                _acc_x = 0.0
            if abs(_vel_y) < 0.5:
                _vel_y = 0.0
                _acc_y = 0.0
            _acc_x += _vel_x * dt
            _acc_y += _vel_y * dt
            step_x = int(_acc_x)
            step_y = int(_acc_y)
            if step_x:
                _acc_x -= step_x
            if step_y:
                _acc_y -= step_y
        if step_x or step_y:
            move_rel(step_x, step_y)


def handle_key(vk: int, is_down: bool, injected: bool = False) -> bool:
    """True = swallow event."""
    global _last_vk, _last_vk_t, _mute_held, _delete_held, _delete_used_as_mod

    # Let our injected Delete through for "tap = real delete"
    if vk == VK_DELETE and injected:
        return False

    # Knob click: exactly one toggle per physical press (ignore BLE double-DOWN)
    if vk == VK_VOLUME_MUTE:
        if is_down:
            if not _mute_held:
                _mute_held = True
                set_mouse_on(not _mouse_on)
        else:
            _mute_held = False
        return True

    # When remap is OFF: do not intercept anything else (normal keyboard)
    if not _mouse_on:
        return False

    # Ctrl + Page Up -> RMB; Ctrl + Delete -> LMB
    if vk == VK_PRIOR and ctrl_held():
        if is_down:
            click_right()
        return True

    if vk == VK_DELETE and ctrl_held():
        if is_down:
            click_left()
        return True

    # Delete held = scroll modifier; short tap (no encoder) = real Delete
    if vk == VK_DELETE:
        if is_down:
            if not _delete_held:
                _delete_held = True
                _delete_used_as_mod = False
        else:
            was_mod = _delete_used_as_mod
            _delete_held = False
            if not was_mod:
                tap_delete()
        return True

    if vk not in (VK_VOLUME_UP, VK_VOLUME_DOWN):
        return False

    if not is_down:
        return True

    now = time.perf_counter()
    if vk == _last_vk and (now - _last_vk_t) * 1000.0 < DEDUPE_MS:
        return True
    _last_vk, _last_vk_t = vk, now
    on_tick(+1 if vk == VK_VOLUME_UP else -1)
    return True


def keyboard_proc(nCode, wParam, lParam):
    if nCode == HC_ACTION:
        info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        vk = info.vkCode
        is_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
        is_up = wParam in (WM_KEYUP, WM_SYSKEYUP)
        injected = bool(info.flags & LLKHF_INJECTED)

        if is_down and vk == VK_Q:
            if (user32.GetAsyncKeyState(VK_CONTROL) & 0x8000) and (
                user32.GetAsyncKeyState(VK_MENU) & 0x8000
            ):
                log("quit hotkey Ctrl+Alt+Q")
                _stop.set()
                if _thread_id:
                    user32.PostThreadMessageW(_thread_id, WM_QUIT, 0, 0)
                return 1

        if (is_down or is_up) and handle_key(vk, is_down, injected):
            return 1

    return user32.CallNextHookEx(_h_kb, nCode, wParam, lParam)


def cleanup() -> None:
    global _h_kb, _delete_held, _mute_held
    _stop.set()
    _delete_held = False
    _mute_held = False
    set_mouse_on(True)
    if _h_kb:
        user32.UnhookWindowsHookEx(_h_kb)
        _h_kb = HHOOK()
        log("hook removed")
    try:
        if PID_FILE.exists() and PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
            PID_FILE.unlink()
    except OSError:
        pass


def main() -> int:
    global _h_kb, _cb_ref, _thread_id
    LOG.write_text("", encoding="utf-8")
    if not ensure_single_instance():
        return 1
    _thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

    log(
        "remap start  turn=X  Ctrl+turn=Y  Del+turn=scroll  "
        "Ctrl+PgUp=RMB  Ctrl+Del=LMB  click encoder=toggle  quit=Ctrl+Alt+Q"
    )
    _cb_ref = HOOKPROC(keyboard_proc)
    _h_kb = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _cb_ref, None, 0)
    if not _h_kb:
        log(f"hook failed err={ctypes.get_last_error()}")
        return 1

    atexit.register(cleanup)
    threading.Thread(target=motion_loop, name="mouse-inertia", daemon=True).start()

    try:
        msg = w.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()
        log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
