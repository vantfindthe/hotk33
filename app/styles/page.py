"""Styles mode's part of the window: pick a ready-made style (the effects
Keychron's Launcher offers) or one of your layouts saved in Paint mode, and
set its color, speed and brightness."""

import time
from tkinter import colorchooser

import customtkinter as ctk
import numpy as np

from music.audiopicker import AudioPicker
from paint.page import DOTS, SWATCHES, hex_color
from paint.pattern import KEYSTROKES, Pattern, render
from widgets import (ACCENT, ACCENT_HOVER, BAD, CARD_BORDER, FAINT, FIELD, FIELD_HOVER, GOOD,
                     MUTED, STAGE, TEXT, TRACK, WARN, DevicePreview)
from .catalog import BY_NAME, STYLES, Context
from .engine import LayoutEngine, StyleEngine, brightness, speed_factor

LAYOUT = "layout:"  # settings["style"] prefix for a layout saved in Paint mode
COLUMNS = 4
DEMO_PRESS_S = 0.7  # the preview of a reactive style "presses" a key this often
DEFAULTS = {
    "style": "Cycle left-right",
    "style_color": [0, 180, 255],
    "style_speed": 50,       # 1..100, 50 = normal
    "style_brightness": 80,  # %
}


def check_settings(settings):
    style = settings["style"]
    if not (style in BY_NAME or (isinstance(style, str) and style.startswith(LAYOUT))):
        settings["style"] = DEFAULTS["style"]


class StylesPage:
    name = "Styles"

    def __init__(self, app, stage, bottom, footer, store):
        """store: Paint mode's LayoutStore (for the saved layouts)."""
        self.app = app
        self.settings = s = app.settings
        self.store = store
        self.outputs = []
        self.out = None
        self.engine = None
        self.hook = None
        self.hook_error = ""
        self.layout_patterns = {}  # device id -> Pattern of the chosen saved layout
        self.started = time.monotonic()
        self.tiles = {}
        f = app.fonts

        # stage: the chosen style on the selected device
        self.stage = ctk.CTkFrame(stage, fg_color=STAGE, corner_radius=16, border_width=1,
                                  border_color=CARD_BORDER)
        self.stage.grid_columnconfigure(0, weight=1)
        self.stage.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(self.stage, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 0))
        head.grid_columnconfigure(1, weight=1)
        self.title = ctk.CTkLabel(head, text="", font=f["bold"], text_color=TEXT, anchor="w")
        self.title.grid(row=0, column=0, sticky="w")
        self.desc = ctk.CTkLabel(head, text="", font=f["small"], text_color=MUTED, anchor="w")
        self.desc.grid(row=0, column=1, sticky="w", padx=12)
        self.preview = DevicePreview(self.stage, scale=app.scale, height=int(240 * app.scale))
        self.preview.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 12))

        # bottom: the styles, the options
        self.bottom = ctk.CTkFrame(bottom, fg_color="transparent")
        self.bottom.grid_columnconfigure(0, weight=3, uniform="styles")
        self.bottom.grid_columnconfigure(1, weight=2, uniform="styles")
        card = app.card(self.bottom, "Styles", row=0, column=0, sticky="nsew", padx=(0, 12))
        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.grid(row=1, column=0, sticky="ew", padx=14)
        for c in range(COLUMNS):
            grid.grid_columnconfigure(c, weight=1, uniform="tiles")
        for i, style in enumerate(STYLES):
            self._tile(grid, style.name, style.name, i)
        app.section(card, "My layouts").grid(row=2, column=0, sticky="w", padx=18, pady=(12, 6))
        self.layouts = ctk.CTkFrame(card, fg_color="transparent")
        self.layouts.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 14))
        for c in range(COLUMNS):
            self.layouts.grid_columnconfigure(c, weight=1, uniform="tiles")

        opts = app.card(self.bottom, "Options", row=0, column=1, sticky="nsew")
        rows = ctk.CTkFrame(opts, fg_color="transparent")
        rows.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))
        rows.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(rows, text="Color", font=f["body"], text_color=TEXT, anchor="w").grid(
            row=0, column=0, sticky="w", pady=4)
        colors = ctk.CTkFrame(rows, fg_color="transparent")
        colors.grid(row=0, column=1, columnspan=2, sticky="w", padx=8)
        self.color_btn = ctk.CTkButton(colors, text="", width=40, height=26, corner_radius=8,
                                       border_width=2, border_color=TEXT,
                                       command=self._choose_color)
        self.color_btn.grid(row=0, column=0, padx=(0, 8))
        for i, c in enumerate(SWATCHES[:7]):
            ctk.CTkButton(colors, text="", width=20, height=20, corner_radius=10, fg_color=c,
                          hover_color=c, command=lambda c=c: self._set_color(c)
                          ).grid(row=0, column=1 + i, padx=2)
        self.color_note = ctk.CTkLabel(rows, text="", font=f["small"], text_color=FAINT,
                                       anchor="w")
        self.color_note.grid(row=1, column=1, columnspan=2, sticky="w", padx=8)
        for r, (key, label) in enumerate((("style_speed", "Speed"),
                                          ("style_brightness", "Brightness")), start=2):
            ctk.CTkLabel(rows, text=label, font=f["body"], text_color=TEXT, anchor="w").grid(
                row=r, column=0, sticky="w", pady=4)
            value = ctk.CTkLabel(rows, text=f"{s[key]}%", font=f["bold"], text_color=TEXT,
                                 anchor="e", width=50)
            value.grid(row=r, column=2, sticky="e")
            slider = ctk.CTkSlider(
                rows, from_=1 if key == "style_speed" else 5, to=100, height=18, fg_color=TRACK,
                progress_color=ACCENT, button_color="#f4f4f8", button_hover_color="#ffffff",
                command=lambda v, k=key, lbl=value: self._on_level(k, v, lbl))
            slider.set(s[key])
            slider.grid(row=r, column=1, sticky="ew", padx=8)
        ctk.CTkLabel(opts, text="Reactive styles light up as you type, anywhere in Windows.",
                     font=f["small"], text_color=FAINT, anchor="w", justify="left",
                     wraplength=380).grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 14))

        # footer: audio, for saved layouts that react to it
        self.footer = AudioPicker(footer, app)
        self.frames = [self.stage, self.bottom, self.footer]
        self._show_color()
        self.refresh_layouts()

    # ------------------------------------------------------------ building

    def _tile(self, parent, text, key, i):
        btn = ctk.CTkButton(parent, text=text, height=30, corner_radius=8,
                            font=self.app.fonts["small"], fg_color=FIELD,
                            hover_color=FIELD_HOVER, text_color=TEXT,
                            command=lambda: self.choose(key))
        btn.grid(row=i // COLUMNS, column=i % COLUMNS, sticky="ew", padx=3, pady=3)
        self.tiles[key] = btn

    def refresh_layouts(self):
        """Lists the layouts saved in Paint mode (they may have changed there)."""
        for key in [k for k in self.tiles if k.startswith(LAYOUT)]:
            self.tiles.pop(key)
        for child in self.layouts.winfo_children():
            child.destroy()
        names = self.store.names()
        for i, name in enumerate(names):
            self._tile(self.layouts, name, LAYOUT + name, i)
        if not names:
            ctk.CTkLabel(self.layouts, text="None yet - paint one in Paint mode and Save it.",
                         font=self.app.fonts["small"], text_color=MUTED, anchor="w").grid(
                row=0, column=0, columnspan=COLUMNS, sticky="w", padx=4)
        style = self.settings["style"]
        if style.startswith(LAYOUT) and style[len(LAYOUT):] not in self.store.saved:
            self.settings["style"] = DEFAULTS["style"]
        self.choose(self.settings["style"], restart=False)

    # ------------------------------------------------------------ choosing

    def choose(self, key, restart=True):
        was_layout = self.settings["style"].startswith(LAYOUT)
        self.settings["style"] = key
        for k, btn in self.tiles.items():
            on = k == key
            btn.configure(fg_color=ACCENT if on else FIELD,
                          hover_color=ACCENT_HOVER if on else FIELD_HOVER)
        if key.startswith(LAYOUT):
            name = key[len(LAYOUT):]
            self.layout_patterns = {}
            self.title.configure(text=name)
            self.desc.configure(text="Your layout from Paint mode")
            self.color_note.configure(text="A layout keeps its own colors")
        else:
            style = BY_NAME[key]
            self.title.configure(text=style.name)
            self.desc.configure(text=style.desc)
            self.color_note.configure(text="" if style.uses_color
                                      else "This style picks its own colors")
            if self.engine and isinstance(self.engine, StyleEngine):
                self.engine.style = style
        if restart and self.engine and was_layout != key.startswith(LAYOUT):
            self.stop()  # a different kind of engine draws it
            self.start()

    def style(self):
        key = self.settings["style"]
        return None if key.startswith(LAYOUT) else BY_NAME[key]

    def pattern_of(self, out):
        """The chosen saved layout's pattern for `out` (render thread safe)."""
        if out is None or out.layout is None:
            return None
        p = self.layout_patterns.get(out.id)
        if p is not None and p.n == out.layout.n:
            return p
        key = self.settings["style"]
        raw = self.store.saved.get(key[len(LAYOUT):], {}).get(out.id) \
            if key.startswith(LAYOUT) else None
        if not raw:
            return None
        try:
            p = Pattern.from_json(raw, out.layout.n)
        except (ValueError, KeyError, TypeError, IndexError):
            return None
        self.layout_patterns[out.id] = p
        return p

    def _show_color(self):
        c = hex_color(self.settings["style_color"])
        self.color_btn.configure(fg_color=c, hover_color=c)

    def _set_color(self, hex_c):
        self.settings["style_color"] = [int(hex_c[i:i + 2], 16) for i in (1, 3, 5)]
        self._show_color()

    def _choose_color(self):
        _, hex_c = colorchooser.askcolor(color=hex_color(self.settings["style_color"]),
                                         parent=self.app.root, title="Style color")
        if hex_c:
            self._set_color(hex_c)

    def _on_level(self, key, value, label):
        self.settings[key] = int(round(value))
        label.configure(text=f"{self.settings[key]}%")

    # ------------------------------------------------------------ devices

    @staticmethod
    def shows(out):
        return out.music or getattr(out, "in_music", False)

    def set_outputs(self, outputs):
        self.outputs = outputs
        self.layout_patterns = {}
        if self.engine:
            self.engine.outputs = self._enabled()

    def _enabled(self):
        return [o for o in self.outputs
                if o.music and o.id not in self.settings["disabled_devices"]]

    def set_enabled(self, out, on):
        if self.engine:
            self.engine.outputs = self._enabled()

    def select(self, out):
        self.out = out if out is not None and out.music else None
        if self.out is None:
            self.preview.set_layout(None)
        else:
            self.preview.set_layout(out.layout, out.name)
        if self.engine:
            self.engine.preview = self.out

    def device_state(self, out):
        if self.engine:
            w = self.engine.workers.get(out.id)
            if w is not None:
                return DOTS[w.state], w.status if w.state == "error" else ""
        return FAINT, ""

    def on_show(self):
        self.refresh_layouts()
        self.footer.refresh()

    # ------------------------------------------------------------ running

    @property
    def running(self):
        return self.engine is not None

    def start(self):
        style = self.style()
        if style is None:
            self.engine = LayoutEngine(self._enabled(), self.pattern_of, self.settings,
                                       self.footer.device_index)
        else:
            self.engine = StyleEngine(self._enabled(), style, self.settings)
        self.engine.preview = self.out
        self.engine.start()

    def stop(self):
        self._set_hook(False)
        if self.engine:
            self.engine.stop()
            self.engine.join(timeout=3)
            self.engine = None

    def _wants_keys(self):
        style = self.style()
        if style is not None:
            return style.reactive
        return any(p.reaction.any() or p.uses(KEYSTROKES)
                   for p in list(self.layout_patterns.values()))

    def _set_hook(self, on):
        if on and self.hook is None:
            from predictive.hook import KeyboardHook
            self.hook = KeyboardHook(self.engine.on_key)
            try:
                self.hook.start()
                self.hook_error = ""
            except OSError as e:
                self.hook_error = str(e)
        elif not on and self.hook is not None:
            self.hook.stop()
            self.hook = None

    def pill(self):
        ws = list(self.engine.workers.values())
        live = sum(w.state == "live" for w in ws)
        if live:
            return f"Live  ·  {live} device{'s' if live > 1 else ''}", GOOD
        if any(w.state == "error" for w in ws):
            return "Device error", BAD
        if ws:
            return "Connecting", MUTED
        return "Nothing to light", WARN

    def message(self):
        return "   ".join(m for m in (self.hook_error,
                                      self.engine.audio_error if self.engine else "") if m)

    def tick(self):
        if self.engine:
            self._set_hook(self._wants_keys())
        out = self.out
        if out is None:
            return
        frame = self.engine.frames.get(out.id) if self.engine else None
        if frame is None:  # not running: preview it (without reactions)
            t = time.monotonic() - self.started
            style = self.style()
            if style is not None:
                heat, presses = self._demo_typing(out.layout.n, t) if style.reactive else (None, ())
                ctx = Context(out.layout, t * speed_factor(self.settings["style_speed"]),
                              np.array(self.settings["style_color"]) / 255, heat, presses)
                frame = style.render(ctx) * brightness(self.settings)
            else:
                p = self.pattern_of(out)
                frame = (np.zeros((out.layout.n, 3)) if p is None else
                         render(p, out.layout, t, max(0.2, self.settings["paint_period"]))
                         * brightness(self.settings))
        self.preview.show(frame)

    @staticmethod
    def _demo_typing(n, t):
        """Made-up key presses (and the heat they'd leave), to preview reactive styles."""
        slot = int(t // DEMO_PRESS_S)
        presses, heat = [], np.zeros(n)
        for k in range(slot, max(-1, slot - 40), -1):
            age = t - k * DEMO_PRESS_S
            led = int((np.sin(k * 12.9898) * 43758.5453) % 1.0 * n)
            if age < 3:
                presses.append((age, led))
            heat[led] += 0.5 * np.exp(-age / 6)
        return heat, presses

    def close(self):
        self.stop()
