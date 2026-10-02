"""Renders the app window in a few scripted states and saves screenshots to docs/.

Nothing you type is involved: the keyboard hook isn't installed and no
keyboard lighting is touched. Run: .venv\\Scripts\\python tools\\screenshots.py
Needs Pillow (pip install pillow).
"""

import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
# a throwaway settings folder: never show (or touch) the real learned data
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="pkl-shots-")

import customtkinter as ctk  # noqa: E402
from PIL import ImageGrab  # noqa: E402

import app as app_mod  # noqa: E402
import devices  # noqa: E402
import keys  # noqa: E402
from engine import DeviceSlot  # noqa: E402
from hook import KeyEvent  # noqa: E402

OUT = ROOT / "docs"
CHAR_VK = {ch: (vk, False) for vk, ch in keys.VK.items() if ch != "space"}
CHAR_VK.update({keys.SHIFTED[ch]: (vk, True) for vk, ch in keys.VK.items() if ch in keys.SHIFTED})
CHAR_VK.update({" ": (0x20, False), "\n": (0x0D, False)})
SHIFT = 0xA0

SCENES = [
    # (file, mode, why (as Auto would show it), text)
    ("english.png", "english", "notepad.exe", "the quick brown fox jumps over th"),
    ("python.png", "python", "code.exe: app.py", "import os\nfor name in os.list"),
    ("powershell.png", "powershell", "windowsterminal.exe: Windows PowerShell",
     "Get-ChildItem -Recurse -Fi"),
    ("private.png", None, None, None),
]


def window_rect(hwnd):
    rect = wintypes.RECT()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def type_text(engine, mode, text):
    """Types `text` in a fixed mode (Auto would re-detect from the fake window)."""
    saved = engine.settings["mode"]
    engine.settings["mode"] = engine.mode = mode
    for ch in text:
        lower = ch.lower() if ch.isalpha() else ch
        vk, shift = CHAR_VK[lower]
        shift = shift or ch.isupper()
        engine._handle(KeyEvent(vk, {SHIFT} if shift else set(), 1))
    engine.settings["mode"] = saved


def main():
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    OUT.mkdir(exist_ok=True)
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    app = app_mod.App(root, live=False)
    app.settings["mode"] = app_mod.AUTO
    app.remember.set(True)
    root.attributes("-topmost", True)
    root.geometry("+40+40")
    eng = app.engine
    app.models.preload()
    # real keyboards, shown as working (this is what the live app shows)
    found, _ = devices.scan_all()
    eng.slots = [DeviceSlot(kb, True) for kb in found]
    for s in eng.slots:
        s.status = "lit"
    # a little learning, so the counters aren't empty
    for mode, sample in (("english", "see you at the standup tomorrow. "),
                         ("python", "prices = fetch_prices(symbol)\n")):
        type_text(eng, mode, sample)

    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    for name, mode, why, text in SCENES:
        with eng.lock:
            if mode is None:
                eng.private = True
                eng.text = ""
            else:
                eng.private = False
                eng.window, eng.text = 1, ""
                type_text(eng, mode, text)
                eng.mode_reason = why
            eng._predict()
            eng.version += 1
        for _ in range(20):
            root.update()
            time.sleep(0.03)
        ImageGrab.grab(bbox=window_rect(hwnd), all_screens=True).save(OUT / name)
        print("saved", OUT / name)
    root.destroy()


if __name__ == "__main__":
    main()
