"""Paint mode's part of the window: the device to paint, the brush, and saved
layouts.

Paint with the mouse (click or drag on the device), or by pressing keys on
the keyboard while Hotk33 is the active window: the brush lands on the key
you press.
"""

import time
from tkinter import colorchooser, messagebox

import customtkinter as ctk
import numpy as np

import keys
from music.audiopicker import AudioPicker
from widgets import (ACCENT, ACCENT_HOVER, BAD, CARD, CARD_BORDER, FAINT, FIELD, FIELD_HOVER,
                     GOOD, INFO, MUTED, STAGE, TEXT, TRACK, WARN)
from .canvas import PaintCanvas
from .engine import PaintEngine
from .pattern import (ANIMATIONS, CIRCLE, KEYSTROKES, REACTS, SQUARE, Brush, Pattern,
                      footprint, render)
from .store import LayoutStore

BRUSH, ERASE, PICK = "Brush", "Erase", "Pick"
UNSAVED = "Unsaved layout"
MAX_UNDO = 50
SWATCHES = ["#ff2a2a", "#ff8a00", "#ffe600", "#3dff4a", "#00e5ff", "#2a5bff", "#b026ff",
            "#ff3dc8", "#ffffff"]
DEFAULTS = {
    "paint_color": [255, 61, 200],
    "paint_animation": "Static",
    "paint_intensity": 100,      # %
    "paint_heat": 0,             # heatmap reaction, %
    "paint_react": "Nothing",    # what else the keys react to: Keystrokes / Audio
    "paint_reactivity": 60,      # %
    "paint_size": 1,             # keys across
    "paint_shape": CIRCLE,
    "paint_weight": 100,         # % the brush's edge gets, compared to its center
    "paint_period": 2.0,         # seconds per animation cycle
    "paint_heat_fade": 1.5,      # seconds for the heatmap to cool down
    "paint_layout": "",          # name of the saved layout being edited
}
# device (worker) state: dot color
DOTS = {"live": GOOD, "resting": INFO, "connecting": WARN, "error": BAD}


def check_settings(settings):
    """Repairs Paint settings edited by hand."""
    for key, allowed in (("paint_animation", ANIMATIONS), ("paint_react", REACTS),
                         ("paint_shape", [CIRCLE, SQUARE])):
        if settings[key] not in allowed:
            settings[key] = DEFAULTS[key]


def hex_color(rgb):
    return "#%02x%02x%02x" % tuple(int(c) for c in rgb)


class PaintPage:
    name = "Paint"

    def __init__(self, app, stage, bottom, footer, layouts_path):
        self.app = app
        self.settings = s = app.settings
        self.store = LayoutStore(layouts_path)
        if s["paint_layout"] not in self.store.saved:
            s["paint_layout"] = ""
        self.raw = dict(self.store.current)  # device id -> saved pattern (JSON)
        self.patterns = {}                   # device id -> Pattern, as painted
        self.dirty = False                   # changed since the layout was saved
        self.undo_stack = []
        self.outputs = []
        self.out = None                      # device being painted
        self.engine = None
        self.hook = None
        self.hook_error = ""
        self.message_text = ""
        self.tool = BRUSH
        self.started = time.monotonic()
        f = app.fonts

        # stage: tools + the paintable device
        self.stage = ctk.CTkFrame(stage, fg_color=STAGE, corner_radius=16, border_width=1,
                                  border_color=CARD_BORDER)
        self.stage.grid_columnconfigure(0, weight=1)
        self.stage.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(self.stage, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 0))
        bar.grid_columnconfigure(5, weight=1)
        self.tool_btn = self._segmented(bar, [BRUSH, ERASE, PICK], self._on_tool)
        self.tool_btn.set(BRUSH)
        self.tool_btn.grid(row=0, column=0)
        for i, (text, cmd) in enumerate((("Fill", self.fill), ("Clear", self.clear),
                                         ("Undo", self.undo))):
            app.small_button(bar, text, cmd, width=56).grid(row=0, column=1 + i, padx=(8, 0))
        self.hint = ctk.CTkLabel(bar, text="", font=f["small"], text_color=FAINT, anchor="e")
        self.hint.grid(row=0, column=5, sticky="e")
        self.canvas = PaintCanvas(self.stage, self._begin_stroke, self._paint_at, self._covers,
                                  scale=app.scale, height=int(240 * app.scale))
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 12))

        # bottom: brush, layouts
        self.bottom = ctk.CTkFrame(bottom, fg_color="transparent")
        self.bottom.grid_columnconfigure(0, weight=3, uniform="paint")
        self.bottom.grid_columnconfigure(1, weight=2, uniform="paint")
        self._build_brush(app.card(self.bottom, "Brush", row=0, column=0, sticky="nsew",
                                   padx=(0, 12)))
        self._build_layouts(app.card(self.bottom, "Layout", row=0, column=1, sticky="nsew"))

        # footer: audio for the audio reaction
        self.footer = AudioPicker(footer, app)
        self.frames = [self.stage, self.bottom, self.footer]

        app.root.bind("<KeyPress>", self._on_key, add="+")
        app.root.bind("<Control-z>", lambda e: self.undo() if app.page is self else None,
                      add="+")
        self._update_hint()

    # ------------------------------------------------------------ building

    def _segmented(self, parent, values, command):
        return ctk.CTkSegmentedButton(
            parent, values=values, command=command, font=self.app.fonts["small"], height=30,
            corner_radius=8, fg_color=FIELD, selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER, unselected_color=FIELD,
            unselected_hover_color=FIELD_HOVER, text_color=TEXT)

    def _label(self, parent, text):
        return ctk.CTkLabel(parent, text=text, font=self.app.fonts["body"], text_color=TEXT,
                            anchor="w")

    def _slider(self, parent, row, col, key, label, lo, hi, fmt, steps=None):
        self._label(parent, label).grid(row=row, column=col * 3, sticky="w", pady=3,
                                        padx=(0 if col == 0 else 18, 0))
        value = ctk.CTkLabel(parent, text=fmt(self.settings[key]), font=self.app.fonts["bold"],
                             text_color=TEXT, anchor="e", width=60)
        value.grid(row=row, column=col * 3 + 2, sticky="e")

        def changed(v):
            v = round(v, 1) if isinstance(self.settings[key], float) else int(round(v))
            self.settings[key] = v
            value.configure(text=fmt(v))
        slider = ctk.CTkSlider(parent, from_=lo, to=hi, number_of_steps=steps or int(hi - lo),
                               height=18, fg_color=TRACK, progress_color=ACCENT,
                               button_color="#f4f4f8", button_hover_color="#ffffff",
                               command=changed)
        slider.set(self.settings[key])
        slider.grid(row=row, column=col * 3 + 1, sticky="ew", padx=8)

        def set_value(v):
            slider.set(v)
            changed(v)
        return set_value

    def _build_brush(self, card):
        s, f = self.settings, self.app.fonts
        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))
        grid.grid_columnconfigure(1, weight=1)

        self._label(grid, "Color").grid(row=0, column=0, sticky="w", pady=4)
        colors = ctk.CTkFrame(grid, fg_color="transparent")
        colors.grid(row=0, column=1, sticky="w")
        self.color_btn = ctk.CTkButton(colors, text="", width=44, height=28, corner_radius=8,
                                       border_width=2, border_color=TEXT,
                                       command=self._choose_color)
        self.color_btn.grid(row=0, column=0, padx=(0, 10))
        for i, c in enumerate(SWATCHES):
            ctk.CTkButton(colors, text="", width=22, height=22, corner_radius=11, fg_color=c,
                          hover_color=c, command=lambda c=c: self._set_color(c)
                          ).grid(row=0, column=1 + i, padx=2)
        self._show_color()

        self._label(grid, "Animation").grid(row=1, column=0, sticky="w", pady=4)
        self.anim_btn = self._segmented(grid, ANIMATIONS,
                                        lambda v: s.__setitem__("paint_animation", v))
        self.anim_btn.set(s["paint_animation"])
        self.anim_btn.grid(row=1, column=1, sticky="w")

        self._label(grid, "React to").grid(row=2, column=0, sticky="w", pady=4)
        self.react_btn = self._segmented(grid, REACTS, self._on_react)
        self.react_btn.set(s["paint_react"])
        self.react_btn.grid(row=2, column=1, sticky="w")

        sliders = ctk.CTkFrame(card, fg_color="transparent")
        sliders.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 14))
        sliders.grid_columnconfigure(1, weight=1)
        sliders.grid_columnconfigure(4, weight=1)
        pct = "{}%".format
        self.sliders = {
            "paint_intensity": self._slider(sliders, 0, 0, "paint_intensity", "Intensity",
                                            0, 100, pct),
            "paint_reactivity": self._slider(sliders, 1, 0, "paint_reactivity", "Reactivity",
                                             0, 100, pct),
            "paint_heat": self._slider(sliders, 2, 0, "paint_heat", "Heatmap", 0, 100, pct),
            "paint_size": self._slider(sliders, 0, 1, "paint_size", "Size", 1, 9,
                                       lambda v: f"{v} key{'s' if v > 1 else ''}"),
            "paint_weight": self._slider(sliders, 1, 1, "paint_weight", "Weight", 0, 100, pct),
        }
        self._label(sliders, "Shape").grid(row=2, column=3, sticky="w", padx=(18, 0))
        self.shape_btn = self._segmented(sliders, [CIRCLE, SQUARE],
                                         lambda v: s.__setitem__("paint_shape", v))
        self.shape_btn.set(s["paint_shape"])
        self.shape_btn.grid(row=2, column=4, columnspan=2, sticky="w", padx=8)
        ctk.CTkLabel(card, text="Heatmap: a key heats up each time it's pressed.  Weight: how "
                                "much the keys around the brush's center take its paint.",
                     font=f["small"], text_color=FAINT, anchor="w", justify="left",
                     wraplength=560).grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 12))

    def _build_layouts(self, card):
        f = self.app.fonts
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=18)
        row.grid_columnconfigure(0, weight=1)
        self.layout_menu = ctk.CTkOptionMenu(
            row, values=[UNSAVED], command=self._on_layout_menu, height=30, font=f["body"],
            dropdown_font=f["body"], corner_radius=8, fg_color=FIELD, button_color=FIELD,
            button_hover_color=FIELD_HOVER, dropdown_fg_color=CARD,
            dropdown_hover_color=FIELD_HOVER, text_color=TEXT, dropdown_text_color=TEXT,
            dynamic_resizing=False)
        self.layout_menu.grid(row=0, column=0, sticky="ew")
        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="w", padx=18, pady=(8, 4))
        for i, (text, cmd) in enumerate((("Save", self.save), ("Save as...", self.save_as),
                                         ("New", self.new), ("Delete", self.delete))):
            self.app.small_button(buttons, text, cmd, width=72).grid(row=0, column=i,
                                                                     padx=(0, 6))
        self.layout_note = ctk.CTkLabel(card, text="", font=f["small"], text_color=MUTED,
                                        anchor="w")
        self.layout_note.grid(row=3, column=0, sticky="ew", padx=20)

        sliders = ctk.CTkFrame(card, fg_color="transparent")
        sliders.grid(row=4, column=0, sticky="ew", padx=18, pady=(8, 14))
        sliders.grid_columnconfigure(1, weight=1)
        secs = "{:.1f} s".format
        self._slider(sliders, 0, 0, "paint_period", "Cycle", 0.3, 6.0, secs, steps=57)
        self._slider(sliders, 1, 0, "paint_heat_fade", "Heat fade", 0.3, 10.0, secs, steps=97)
        self._refresh_layouts()

    # ------------------------------------------------------------ brush

    def brush(self):
        s = self.settings
        return Brush(np.array(s["paint_color"]) / 255, ANIMATIONS.index(s["paint_animation"]),
                     s["paint_intensity"] / 100, s["paint_heat"] / 100,
                     REACTS.index(s["paint_react"]), s["paint_reactivity"] / 100,
                     s["paint_size"], s["paint_shape"], s["paint_weight"] / 100)

    def _show_color(self):
        c = hex_color(self.settings["paint_color"])
        self.color_btn.configure(fg_color=c, hover_color=c)

    def _set_color(self, hex_c):
        self.settings["paint_color"] = [int(hex_c[i:i + 2], 16) for i in (1, 3, 5)]
        self._show_color()
        if self.tool != BRUSH:
            self.tool_btn.set(BRUSH)
            self._on_tool(BRUSH)

    def _choose_color(self):
        rgb, hex_c = colorchooser.askcolor(color=hex_color(self.settings["paint_color"]),
                                           parent=self.app.root, title="Brush color")
        if hex_c:
            self._set_color(hex_c)

    def _on_react(self, value):
        self.settings["paint_react"] = value
        if value != REACTS[0] and self.settings["paint_reactivity"] == 0:
            self.settings["paint_reactivity"] = 60
            self.sliders["paint_reactivity"](60)

    def _on_tool(self, tool):
        self.tool = tool
        self._update_hint()

    def _load_brush(self, b):
        """Pick: the brush takes the picked key's paint."""
        s = self.settings
        s["paint_color"] = [int(round(v * 255)) for v in b.color]
        s["paint_animation"] = ANIMATIONS[b.animation]
        s["paint_intensity"] = int(round(b.intensity * 100))
        s["paint_heat"] = int(round(b.reaction * 100))
        s["paint_react"] = REACTS[b.react]
        s["paint_reactivity"] = int(round(b.reactivity * 100))
        self._show_color()
        self.anim_btn.set(s["paint_animation"])
        self.react_btn.set(s["paint_react"])
        for key in ("paint_intensity", "paint_heat", "paint_reactivity"):
            self.sliders[key](s[key])

    # ------------------------------------------------------------ patterns

    def pattern_of(self, out, create=False):
        """The pattern painted on `out`, or None. Safe from the render thread."""
        if out is None or out.layout is None:
            return None
        n = out.layout.n
        p = self.patterns.get(out.id)
        if p is not None and p.n == n:
            return p
        p = None
        raw = self.raw.get(out.id)
        if raw:
            try:
                p = Pattern.from_json(raw, n)
            except (ValueError, KeyError, TypeError, IndexError):
                p = None
        if p is None and create:
            p = Pattern(n)
        if p is not None:
            self.patterns[out.id] = p
        return p

    def layout_json(self):
        data = dict(self.raw)
        for out_id, p in list(self.patterns.items()):
            if p.empty:
                data.pop(out_id, None)
            else:
                data[out_id] = p.to_json()
        return data

    def _begin_stroke(self):
        p = self.pattern_of(self.out, create=True)
        if p is not None:
            self.undo_stack = (self.undo_stack + [(self.out.id, p.copy())])[-MAX_UNDO:]

    def _covers(self, led):
        s = self.settings
        if self.out is None or self.tool == PICK:
            return [led]
        size = s["paint_size"]
        idx, _ = footprint(self.out.layout, led, size, s["paint_shape"], s["paint_weight"] / 100)
        return idx

    def _paint_at(self, led):
        out = self.out
        p = self.pattern_of(out, create=True)
        if p is None or led >= p.n:
            return
        if self.tool == PICK:
            self._load_brush(p.pick(led))
            self.tool_btn.set(BRUSH)
            self._on_tool(BRUSH)
            return
        b = self.brush()
        idx, strengths = footprint(out.layout, led, b.size, b.shape, b.weight)
        if self.tool == ERASE:
            p.erase(idx, strengths)
        else:
            p.paint(idx, strengths, b)
        self._changed()

    def _changed(self):
        if not self.dirty:
            self.dirty = True
            self._refresh_layouts()

    def fill(self):
        p = self.pattern_of(self.out, create=True)
        if p is None:
            return
        self._begin_stroke()
        if self.tool == ERASE:
            p.erase(np.arange(p.n), np.ones(p.n))
        else:
            p.paint(np.arange(p.n), np.ones(p.n), self.brush())
        self._changed()

    def clear(self):
        p = self.pattern_of(self.out)
        if p is None or p.empty:
            return
        self._begin_stroke()
        p.erase(np.arange(p.n), np.ones(p.n))
        self._changed()

    def undo(self):
        if not self.undo_stack:
            return
        out_id, saved = self.undo_stack.pop()
        p = self.patterns.get(out_id)
        if p is not None and p.n == saved.n:
            p.color[:], p.animation[:] = saved.color, saved.animation
            p.intensity[:], p.reaction[:] = saved.intensity, saved.reaction
            p.react[:], p.reactivity[:] = saved.react, saved.reactivity
            self._changed()

    def _on_key(self, event):
        """Paint by keystroke: the brush lands on the key pressed."""
        if self.app.page is not self or event.state & 0x4:  # Ctrl: shortcuts
            return
        if "entry" in event.widget.winfo_class().lower():
            return
        key = {"Return": "enter", "KP_Enter": "enter", "space": "space"}.get(event.keysym)
        if key is None and event.char:
            key = keys.char_key(event.char)
        out = self.out
        if key is None or out is None:
            return
        leds = [i for i in out.keymap.get(key, []) if i < out.layout.n]
        if not leds:
            self.message_text = (f"{out.name} has no key map - paint it with the mouse"
                                 if not out.keymap else "")
            return
        self.message_text = ""
        if self.tool == PICK:
            self._paint_at(leds[0])
            return
        self._begin_stroke()
        for led in leds:
            self._paint_at(led)

    # ------------------------------------------------------------ layouts

    def _refresh_layouts(self):
        names = self.store.names()
        current = self.settings["paint_layout"]
        self.layout_menu.configure(values=[UNSAVED] + names)
        self.layout_menu.set(current or UNSAVED)
        if not current:
            note = "Not saved yet" if self.layout_json() else "Paint something, then Save"
        else:
            note = "Unsaved changes" if self.dirty else "Saved"
        self.layout_note.configure(text=note)

    def _confirm_discard(self):
        return not self.dirty or messagebox.askyesno(
            "Discard changes", "Discard the changes to this layout?", parent=self.app.root)

    def _set_layout(self, name, data):
        self.raw = dict(data)
        self.patterns = {}
        self.undo_stack = []
        self.settings["paint_layout"] = name
        self.dirty = False
        self._refresh_layouts()

    def _on_layout_menu(self, choice):
        if choice == (self.settings["paint_layout"] or UNSAVED):
            return
        if choice == UNSAVED or not self._confirm_discard():
            self._refresh_layouts()
            return
        self._set_layout(choice, self.store.saved.get(choice, {}))

    def save(self):
        name = self.settings["paint_layout"]
        if not name:
            self.save_as()
            return
        self.store.saved[name] = self.layout_json()
        self._write()
        self.dirty = False
        self._refresh_layouts()

    def save_as(self):
        name = ctk.CTkInputDialog(text="Name for this layout:", title="Save layout").get_input()
        name = (name or "").strip()
        if not name:
            return
        if name in self.store.saved and not messagebox.askyesno(
                "Replace layout", f"Replace the saved layout \"{name}\"?", parent=self.app.root):
            return
        self.settings["paint_layout"] = name
        self.save()

    def new(self):
        if self._confirm_discard():
            self._set_layout("", {})

    def delete(self):
        name = self.settings["paint_layout"]
        if not name or not messagebox.askyesno(
                "Delete layout", f"Delete the saved layout \"{name}\"? What's painted stays "
                                 "on screen, unsaved.", parent=self.app.root):
            return
        del self.store.saved[name]
        self.settings["paint_layout"] = ""
        self.dirty = True
        self._write()
        self._refresh_layouts()

    def _write(self):
        self.store.current = self.layout_json()
        self.store.write()

    # ------------------------------------------------------------ devices

    @staticmethod
    def shows(out):
        return out.music or getattr(out, "in_music", False)

    def set_outputs(self, outputs):
        self.outputs = outputs
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
            self.canvas.set_layout(None)
        else:
            self.canvas.set_layout(out.layout, out.name)
        if self.engine:
            self.engine.preview = self.out
        self._update_hint()

    def _update_hint(self):
        if self.out is None:
            text = "Pick a device in the list to paint it"
        elif self.tool == PICK:
            text = "Click a key to take its paint"
        elif self.out.keymap:
            text = "Click or drag to paint  ·  or press keys while Hotk33 is active"
        else:
            text = "Click or drag to paint"
        self.hint.configure(text=text)

    def device_state(self, out):
        if self.engine:
            w = self.engine.workers.get(out.id)
            if w is not None:
                return DOTS[w.state], w.status if w.state == "error" else ""
        return FAINT, ""

    # ------------------------------------------------------------ running

    @property
    def running(self):
        return self.engine is not None

    def start(self):
        self.engine = PaintEngine(self._enabled(), self.pattern_of, self.settings,
                                  self.footer.device_index)
        self.engine.preview = self.out
        self.engine.start()

    def stop(self):
        self._set_hook(False)
        if self.engine:
            self.engine.stop()
            self.engine.join(timeout=3)
            self.engine = None
        self._write()

    def _wants_keys(self):
        """Keystrokes are read only while something painted reacts to them."""
        return any(p.reaction.any() or p.uses(KEYSTROKES) for p in list(self.patterns.values()))

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

    def on_show(self):
        self.footer.refresh()  # Music mode may have changed the audio source

    def pill(self):
        ws = list(self.engine.workers.values())
        live = sum(w.state == "live" for w in ws)
        if live:
            return f"Live  ·  {live} device{'s' if live > 1 else ''}", GOOD
        if any(w.state == "error" for w in ws):
            return "Device error", BAD
        if ws:
            return "Connecting", MUTED
        return "Paint something to light it up", WARN

    def message(self):
        errors = [m for m in (self.hook_error, self.engine.audio_error if self.engine else "",
                              self.message_text) if m]
        return "   ".join(errors)

    def tick(self):
        if self.engine:
            self._set_hook(self._wants_keys())
        out = self.out
        if out is None:
            return
        frame = self.engine.frames.get(out.id) if self.engine else None
        if frame is None:
            p = self.pattern_of(out)
            if p is None:
                frame = np.zeros((out.layout.n, 3))
            else:  # not running: preview the animations (no reactions)
                frame = render(p, out.layout, time.monotonic() - self.started,
                               max(0.2, self.settings["paint_period"]))
        self.canvas.show(frame)

    def close(self):
        self.stop()
