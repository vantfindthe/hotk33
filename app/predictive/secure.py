"""Detects when the focused input is a password field, so keystrokes typed
into it are never recorded, learned or hinted at on the keyboard.

Uses UI Automation (browsers, modern apps, WPF/UWP, Windows sign-in prompts)
and, as a fallback, the ES_PASSWORD style of classic Win32 edit boxes.
"""

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
GWL_STYLE = -16
ES_PASSWORD = 0x20


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]


class PasswordDetector:
    """Create and use on one thread (UI Automation is a COM API)."""

    def __init__(self):
        self.uia = None
        try:
            import comtypes
            import comtypes.client
            try:
                comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            except OSError:
                pass  # COM already initialized on this thread, in another mode
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as uia
            try:
                self.uia = comtypes.client.CreateObject(uia.CUIAutomation8,
                                                        interface=uia.IUIAutomation2)
                # a hung app must not stall the lights for long
                self.uia.ConnectionTimeout = 500
                self.uia.TransactionTimeout = 500
            except (OSError, AttributeError):
                self.uia = comtypes.client.CreateObject(uia.CUIAutomation,
                                                        interface=uia.IUIAutomation)
        except Exception:  # noqa: BLE001 - fall back to the Win32 check only
            self.uia = None

    def focused_is_password(self):
        if self.uia is not None:
            try:
                if self.uia.GetFocusedElement().CurrentIsPassword:
                    return True
            except Exception:  # noqa: BLE001 - COMError, timeouts, elements going away
                pass
        info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
        if not (user32.GetGUIThreadInfo(0, ctypes.byref(info)) and info.hwndFocus):
            return False
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(info.hwndFocus, cls, 64)
        if "edit" not in cls.value.lower():  # the style bit means something else elsewhere
            return False
        return bool(user32.GetWindowLongW(info.hwndFocus, GWL_STYLE) & ES_PASSWORD)
