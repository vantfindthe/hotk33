"""Renders the Hotk33 window in a few scripted states and saves screenshots to docs/.

Nothing you type is involved and no lighting is touched: the keyboard hook
isn't installed, devices are simulated (never opened), the music is a made-up
spectrum and the typing is scripted. Run: .venv\\Scripts\\python tools\\screenshots.py
"""

import ctypes
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
# a throwaway settings folder: never show (or touch) the real settings and learned data
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="hotk33-shots-")

import customtkinter as ctk  # noqa: E402
import numpy as np  # noqa: E402
from PIL import ImageGrab  # noqa: E402

import app as app_mod  # noqa: E402
import keys  # noqa: E402
import layout  # noqa: E402
from devices import hardware  # noqa: E402
from devices.base import Output  # noqa: E402
from devices.logitech import LogitechKeyboard  # noqa: E402
from devices.model100 import Model100  # noqa: E402
from music import effects  # noqa: E402
from music.engine import palette_for  # noqa: E402
from predictive.hook import KeyEvent  # noqa: E402
from widgets import FIELD, FIELD_HOVER, GOOD, TEXT  # noqa: E402

OUT = ROOT / "docs"
CHAR_VK = {ch: (vk, False) for vk, ch in keys.VK.items() if ch != "space"}
CHAR_VK.update({keys.SHIFTED[ch]: (vk, True) for vk, ch in keys.VK.items() if ch in keys.SHIFTED})
CHAR_VK.update({" ": (0x20, False), "\n": (0x0D, False)})
SHIFT = 0xA0

TYPING_SCENES = [
    # (file, mode, why (as Auto would show it), text)
    ("english.png", "english", "notepad.exe", "the quick brown fox jumps over th"),
    ("python.png", "python", "code.exe: app.py", "import os\nfor name in os.list"),
    ("powershell.png", "powershell", "windowsterminal.exe: Windows PowerShell",
     "Get-ChildItem -Recurse -Fi"),
    ("private.png", None, None, None),
]


class Strip(Output):
    """A simulated ARGB strip."""

    def __init__(self):
        self.id, self.name = "demo:strip", "ARGB LED strip"
        self.detail = "OpenRGB · LED Strip · 60 LEDs"
        self.layout = layout.strip(60)

    def send(self, rgb):
        pass


class Spectrum:
    """A made-up moment of music, for the effects to render."""

    num_bands = 16
    bands = np.clip(0.95 - np.linspace(0, 0.75, 16) + 0.12 * np.sin(np.arange(16)), 0, 1)
    vu = np.array([0.8, 0.75])
    bass, beat, silent = 0.9, False, False


def devices():
    return [Model100("COM5"), LogitechKeyboard("G610 Orion"), Strip(),
            hardware.SetupHint("Keychron", "Keychron Q1", hardware.SETUP_HINTS["Keychron"],
                               in_music=False)]


def type_text(engine, mode, text):
    """Types `text` in a fixed mode (Auto would re-detect from the fake window)."""
    saved = engine.settings["typing_mode"]
    engine.settings["typing_mode"] = engine.mode = mode
    for ch in text:
        lower = ch.lower() if ch.isalpha() else ch
        vk, shift = CHAR_VK[lower]
        shift = shift or ch.isupper()
        engine._handle(KeyEvent(vk, {SHIFT} if shift else set(), 1))
    engine.settings["typing_mode"] = saved


def grab(root, path):
    for _ in range(20):
        root.update()
        time.sleep(0.03)
    x, y = root.winfo_rootx(), root.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height()),
                   all_screens=sys.platform == "win32").save(path)
    print("saved", path)


def main():
    if sys.platform == "win32":
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    OUT.mkdir(exist_ok=True)
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    app = app_mod.App(root, live=False)
    app.tick = lambda: None  # no live updates: each scene is set up by hand
    root.attributes("-topmost", True)
    root.geometry("1180x900+40+40")
    app._apply_scan(devices(), [])

    # Music: the Model 100 showing the Bars effect, "playing"
    music = app.pages[app_mod.MUSIC]
    out = app.selected
    palette, spatial = palette_for(app.settings)
    colors = effects.render(effects.EFFECTS["Bars"](), out.layout, Spectrum, palette, spatial)
    music.preview.show(np.clip(colors, 0, 1) * 0.9)
    music.eq.set_levels(Spectrum.bands, music.band_colors)
    app._set_pill("Live  ·  3 devices  ·  50 fps", GOOD)
    app.start_btn.configure(text="Stop", fg_color=FIELD, hover_color=FIELD_HOVER, text_color=TEXT)
    for r in app.rows.values():
        if r["out"].available:
            r["dot"].configure(text_color=GOOD)
    app.detail.configure(text="")
    grab(root, OUT / "music.png")

    # Paint: a layout painted on the Model 100, with the brush hovering over J
    app.mode_btn.set(app_mod.PAINT)
    app.switch_page(app_mod.PAINT)
    paint = app.pages[app_mod.PAINT]
    kb = paint.out
    st = app.settings

    def stroke(keys_, **brush):
        st.update({"paint_size": 1, "paint_shape": "Circle", "paint_weight": 100,
                   "paint_animation": "Static", "paint_react": "Nothing", "paint_heat": 0,
                   **brush})
        for k in keys_:
            for led in kb.keymap.get(k, []):
                paint._paint_at(led)

    st.update(paint_color=[40, 70, 255], paint_intensity=55, paint_animation="Static")
    paint.fill()
    stroke("1234567890", paint_color=[255, 255, 255], paint_animation="Rainbow",
           paint_intensity=100)
    stroke("wasd", paint_color=[255, 40, 40], paint_intensity=100, paint_heat=80)
    stroke("j", paint_color=[0, 229, 255], paint_intensity=100, paint_size=3,
           paint_weight=35, paint_react="Keystrokes", paint_reactivity=60)
    st.update(paint_color=[255, 61, 200], paint_size=3, paint_shape="Circle", paint_weight=35,
              paint_react="Keystrokes")
    paint._load_brush(paint.brush())
    paint.sliders["paint_size"](3)
    paint.sliders["paint_weight"](35)
    paint.anim_btn.set("Static")
    paint.dirty = False
    paint.settings["paint_layout"] = "Gaming"
    paint.store.saved["Gaming"] = paint.layout_json()
    paint._refresh_layouts()
    paint.canvas.hover = list(paint._covers(kb.keymap["j"][0]))
    paint.tick()
    app._set_pill("Live  ·  1 device", GOOD)
    app.start_btn.configure(text="Stop", fg_color=FIELD, hover_color=FIELD_HOVER, text_color=TEXT)
    grab(root, OUT / "paint.png")
    app.mode_btn.set(app_mod.MUSIC)
    app.switch_page(app_mod.MUSIC)

    # Typing: shown as running, without the keyboard hook or any lighting
    app.mode_btn.set(app_mod.TYPING)
    app.switch_page(app_mod.TYPING)
    typing = app.pages[app_mod.TYPING]
    eng = typing.engine
    eng._stop = False
    app._update_run_state()
    typing.models.preload()
    for s in eng.slots:
        s.status = "lit"
    # a little learning, so the counters aren't empty
    for mode, sample in (("english", "see you at the standup tomorrow. "),
                         ("python", "prices = fetch_prices(symbol)\n")):
        type_text(eng, mode, sample)
    for name, mode, why, text in TYPING_SCENES:
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
        typing.refresh()
        app._update_rows()
        app._set_pill(*typing.pill())
        app.detail.configure(text=typing.message())
        grab(root, OUT / name)
    eng._stop = True
    root.destroy()


if __name__ == "__main__":
    main()
