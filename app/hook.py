"""System-wide keystroke listener (a Windows low-level keyboard hook).

Only key presses are reported, with the modifier state at the time; nothing
is blocked or changed. The hook runs on its own thread with a message loop.
"""

import ctypes
import threading
from ctypes import wintypes

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
WM_QUIT = 0x12
SHIFT = (0x10, 0xA0, 0xA1)
CTRL = (0x11, 0xA2, 0xA3)
ALT = (0x12, 0xA4, 0xA5)
WIN = (0x5B, 0x5C)
MODIFIERS = set(SHIFT + CTRL + ALT + WIN)

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT,
                               wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM,
                                      wintypes.LPARAM]
user32.GetForegroundWindow.restype = wintypes.HWND
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class KeyEvent:
    __slots__ = ("vk", "shift", "ctrl", "alt", "win", "window")

    def __init__(self, vk, held, window):
        self.vk = vk
        self.shift = bool(held & set(SHIFT))
        self.ctrl = bool(held & set(CTRL))
        self.alt = bool(held & set(ALT))
        self.win = bool(held & set(WIN))
        self.window = window


FKEYS = {f"f{i}": 0x6F + i for i in range(1, 25)}
NAMED_VK = {"pause": 0x13, "scrolllock": 0x91, "insert": 0x2D, "space": 0x20, **FKEYS}


def parse_hotkey(text):
    """"ctrl+alt+p" -> (frozenset of modifier names, virtual-key code)."""
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    mods = frozenset(p for p in parts if p in ("ctrl", "alt", "shift", "win"))
    keys = [p for p in parts if p not in mods]
    if len(keys) != 1:
        raise ValueError(f"hotkey {text!r} needs exactly one non-modifier key")
    key = keys[0]
    if key in NAMED_VK:
        return mods, NAMED_VK[key]
    if len(key) == 1 and key.isalnum():
        return mods, ord(key.upper())
    raise ValueError(f"unknown key {key!r} in hotkey {text!r}")


def format_hotkey(text):
    return "+".join(p.strip().capitalize() for p in text.split("+"))


class KeyboardHook:
    """Calls on_key(KeyEvent) for every key press, from the hook thread.
    on_key must return quickly - Windows drops slow hooks.

    hotkeys: {(modifier names, vk): callback}. A matching press calls the
    callback (which must also be quick) and is swallowed, so the focused app
    never sees it."""

    def __init__(self, on_key, hotkeys=None):
        self.on_key = on_key
        self.hotkeys = dict(hotkeys or {})
        self.held = set()
        self._thread = None
        self._thread_id = None
        self._ready = threading.Event()
        self._error = None
        self._proc = HOOKPROC(self._callback)  # keep a reference: ctypes won't

    def start(self):
        self._thread = threading.Thread(target=self._run, name="keyboard-hook", daemon=True)
        self._thread.start()
        self._ready.wait(5)
        if self._error:
            raise OSError(self._error)

    def stop(self):
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(2)

    def _run(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc,
                                        kernel32.GetModuleHandleW(None), 0)
        if not hook:
            self._error = f"Couldn't install the keyboard hook (error {ctypes.get_last_error()})"
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(hook)

    def _callback(self, code, wparam, lparam):
        if code == 0:
            try:
                kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                vk = kb.vkCode
                if wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    if vk in MODIFIERS:
                        self.held.add(vk)
                    else:
                        # drop modifiers whose key-up we missed (e.g. Win+L)
                        for m in [m for m in self.held if not user32.GetAsyncKeyState(m) & 0x8000]:
                            self.held.discard(m)
                        ev = KeyEvent(vk, self.held, user32.GetForegroundWindow())
                        mods = frozenset(name for name, on in (("ctrl", ev.ctrl), ("alt", ev.alt),
                                                               ("shift", ev.shift), ("win", ev.win))
                                         if on)
                        action = self.hotkeys.get((mods, vk))
                        if action is not None:
                            action()
                            return 1  # swallow the hotkey
                        self.on_key(ev)
                elif wparam in (WM_KEYUP, WM_SYSKEYUP):
                    self.held.discard(vk)
            except Exception:  # noqa: BLE001 - never let an error break typing
                pass
        return user32.CallNextHookEx(None, code, wparam, lparam)
