"""Picks the prediction mode for the window being typed in (Auto mode).

Terminals are recognized by their program (and, for hosts like Windows
Terminal, by the tab title); editors and IDEs by the file name in their title
bar. Everything else is English.
"""

import ctypes
import re
from ctypes import wintypes

from predict import ENGLISH

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

SHELLS = {
    "powershell.exe": "powershell", "pwsh.exe": "powershell", "powershell_ise.exe": "powershell",
    "cmd.exe": "cmd",
    "mintty.exe": "bash", "bash.exe": "bash", "wsl.exe": "bash", "wslhost.exe": "bash",
    "git-bash.exe": "bash", "ubuntu.exe": "bash", "debian.exe": "bash",
}
# Programs that host a shell; the tab/window title tells which one.
TERMINAL_HOSTS = {"windowsterminal.exe", "openconsole.exe", "conhost.exe", "wezterm-gui.exe",
                  "alacritty.exe", "tabby.exe", "hyper.exe", "conemu64.exe", "conemu.exe",
                  "cmder.exe", "fluentterminal.exe"}
TITLE_SHELLS = [
    (re.compile(r"powershell|pwsh|\bPS [A-Z]:\\", re.I), "powershell"),
    (re.compile(r"command prompt|cmd\.exe|\\system32\\cmd", re.I), "cmd"),
    (re.compile(r"mingw|msys|bash|ubuntu|debian|wsl|zsh|\w@[\w.-]+:|^~|:\s*~", re.I), "bash"),
]
# Their titles name web pages, not files being edited.
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe",
            "arc.exe", "iexplore.exe"}
_FILE_IN_TITLE = re.compile(r"[\w.-]+\.([A-Za-z0-9]{1,5})\b")


def _title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _exe(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


class Detector:
    def __init__(self, index):
        """index: mode id -> {"name", "exts"} (see predict.Models.index)."""
        self.by_ext = {}
        for mode, info in index.items():
            for ext in info.get("exts", []):
                self.by_ext.setdefault(ext.lower().lstrip("."), mode)
        self.available = set(index)
        self._exes = {}
        self._last = None

    def detect(self, hwnd):
        """(mode id, short description of why)."""
        if not hwnd:
            return ENGLISH, "no window"
        exe = self._exes.get(hwnd)
        if exe is None:
            exe = self._exes[hwnd] = _exe(hwnd)
            if len(self._exes) > 500:
                self._exes.clear()
        title = _title(hwnd)
        if self._last and self._last[0] == (hwnd, title):
            return self._last[1]
        result = self._decide(exe, title)
        if result[0] not in self.available:
            result = (ENGLISH, result[1] + " (no model - using English)")
        self._last = ((hwnd, title), result)
        return result

    def _decide(self, exe, title):
        app = exe or "unknown app"
        if exe in SHELLS:
            return SHELLS[exe], app
        if exe in TERMINAL_HOSTS:
            for pattern, mode in TITLE_SHELLS:
                if pattern.search(title):
                    return mode, f"{app}: {title[:40]}"
            return "powershell", f"{app} (assumed PowerShell)"
        if exe in BROWSERS:
            return ENGLISH, app
        for m in _FILE_IN_TITLE.finditer(title):
            mode = self.by_ext.get(m.group(1).lower())
            if mode:
                return mode, f"{app}: {m.group(0)}"
        return ENGLISH, app
