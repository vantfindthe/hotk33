"""Typing mode's part of the window: what you typed, the next-key guesses on
a keyboard, the prediction mode, learning and privacy."""

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

import keys
from widgets import (BAD, CARD, CARD_BORDER, FAINT, FIELD, FIELD_HOVER, FONT, GOOD,
                     INFO, KEY_OFF, MUTED, STAGE, TEXT, WARN, blend, rounded_points)
from .engine import AUTO, Engine
from .hook import KeyboardHook, format_hotkey, parse_hotkey
from .modes import Detector
from .predict import Models

MONO = "Cascadia Mono"
KEY_TEXT = "#7c7c8c"
AUTOSAVE_S = 60
DEFAULTS = {
    "typing_mode": AUTO,             # "auto" (by window) or a mode id
    "key_colors": [[0, 255, 0], [255, 190, 0], [255, 0, 0]],  # 1st, 2nd, 3rd guess
    "white_levels": [255, 80, 18],   # same, for white-only keyboards (G610)
    "remember_words": False,         # keep learned words between sessions
    "show_text": True,               # show the typed context in the window
    "private_hotkey": "ctrl+alt+p",  # stop reading keystrokes until pressed again
    "hotkey_sound": True,            # beep up / down when private mode switches
    "idle_release_s": 0,             # give keyboards their own lighting back after
                                     # this many idle seconds (0 = never)
}
# slot status: dot color
DOTS = {"lit": GOOD, "idle": INFO, "ready": WARN}


def hex_color(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


class TypingPage:
    name = "Typing"
    KEY_W = 46    # key size before DPI scaling
    GAP = 6

    def __init__(self, app, stage, bottom, footer, learned_path, live=True):
        """live=False (screenshots): no keyboard hook, no lighting."""
        self.app = app
        self.settings = app.settings
        self.learned_path = learned_path
        self.live = live
        learned = learned_path if self.settings["remember_words"] else None
        self.models = Models(Path(__file__).resolve().parent, learned)
        self.mode_names = self.models.names()
        if self.settings["typing_mode"] not in self.mode_names:
            self.settings["typing_mode"] = AUTO
        self.engine = Engine(self.models, Detector(self.models.index), self.settings)
        self.engine.on_private = self._private_sound
        self.hook = None
        self.hotkey_label = format_hotkey(self.settings["private_hotkey"])
        self.hotkey_error = ""
        self.seen_version = -1
        self.saved_at = time.monotonic()
        self._preloading = False
        f = app.fonts

        # stage: mode, typed text + guesses, keyboard
        self.stage = ctk.CTkFrame(stage, fg_color=STAGE, corner_radius=16, border_width=1,
                                  border_color=CARD_BORDER)
        self.stage.grid_columnconfigure(0, weight=1)
        self.stage.grid_rowconfigure(2, weight=1)
        row = ctk.CTkFrame(self.stage, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        row.grid_columnconfigure(2, weight=1)
        app.section(row, "Predict").grid(row=0, column=0, padx=(0, 10))
        self.mode_choices = {"Auto - follow the window I'm typing in": AUTO}
        self.mode_choices.update({name: m for m, name in self.mode_names.items()})
        current = next(label for label, m in self.mode_choices.items()
                       if m == self.settings["typing_mode"])
        ctk.CTkOptionMenu(row, values=list(self.mode_choices), command=self.choose_mode,
                          variable=tk.StringVar(value=current), width=300, height=30,
                          fg_color=FIELD, button_color=FIELD, button_hover_color=FIELD_HOVER,
                          dropdown_fg_color=CARD, dropdown_hover_color=FIELD_HOVER,
                          text_color=TEXT, dropdown_text_color=TEXT, font=f["body"],
                          dropdown_font=f["body"], corner_radius=8,
                          dynamic_resizing=False).grid(row=0, column=1)
        self.mode_label = ctk.CTkLabel(row, text="", text_color=MUTED, font=f["small"],
                                       anchor="w")
        self.mode_label.grid(row=0, column=2, sticky="ew", padx=12)

        row = ctk.CTkFrame(self.stage, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=20, pady=(8, 0))
        row.grid_columnconfigure(0, weight=1)
        self.context = ctk.CTkLabel(row, text="", text_color=TEXT, font=(MONO, 17),
                                    anchor="w")
        self.context.grid(row=0, column=0, sticky="ew")
        self.chips = []
        for i, caption in enumerate(("1st", "2nd", "3rd")):
            col = ctk.CTkFrame(row, fg_color="transparent")
            col.grid(row=0, column=1 + i, padx=(8, 0))
            chip = ctk.CTkLabel(col, text="", width=46, height=40, corner_radius=10,
                                fg_color=KEY_OFF, text_color="#0b0d10",
                                font=(FONT, 18, "bold"))
            chip.pack()
            ctk.CTkLabel(col, text=caption, text_color=MUTED, font=(FONT, 10),
                         height=14).pack()
            self.chips.append(chip)
        self._build_keyboard(self.stage)

        # bottom: learning, privacy
        self.bottom = ctk.CTkFrame(bottom, fg_color="transparent")
        self.bottom.grid_columnconfigure(0, weight=1, uniform="typing")
        self.bottom.grid_columnconfigure(1, weight=1, uniform="typing")

        learn = app.card(self.bottom, "Learning", row=0, column=0, sticky="nsew", padx=(0, 12))
        self.learned_label = ctk.CTkLabel(learn, text="", text_color=TEXT, font=f["small"],
                                          anchor="w", justify="left", wraplength=420)
        self.learned_label.grid(row=1, column=0, sticky="ew", padx=18)
        self.remember = app.switch(learn, "Remember between sessions", self.toggle_remember)
        if self.settings["remember_words"]:
            self.remember.select()
        self.remember.grid(row=2, column=0, sticky="w", padx=18, pady=(10, 6))
        ctk.CTkButton(learn, text="Forget everything learned", height=28, corner_radius=8,
                      fg_color=FIELD, hover_color=blend(BAD, FIELD, 0.35), text_color=TEXT,
                      font=f["small"], command=self.forget
                      ).grid(row=3, column=0, sticky="w", padx=18, pady=(4, 14))

        privacy = app.card(self.bottom, "Privacy", row=0, column=1, sticky="nsew")
        ctk.CTkLabel(privacy, text="Password fields are skipped automatically: nothing typed "
                                   "there is read, and every key goes dark. For prompts Windows "
                                   "can't see as password fields, use private mode.",
                     text_color=MUTED, font=f["small"], anchor="w", justify="left",
                     wraplength=420).grid(row=1, column=0, sticky="ew", padx=18)
        self.private_btn = ctk.CTkButton(privacy, text="", height=32, corner_radius=8,
                                         fg_color=FIELD, hover_color=FIELD_HOVER,
                                         text_color=TEXT, font=f["body"],
                                         command=self.toggle_private)
        self.private_btn.grid(row=2, column=0, sticky="w", padx=18, pady=(10, 6))
        self.show_text = app.switch(privacy, "Show typed text", self.toggle_show_text)
        if self.settings["show_text"]:
            self.show_text.select()
        self.show_text.grid(row=3, column=0, sticky="w", padx=18, pady=(4, 14))

        self.footer = ctk.CTkFrame(footer, fg_color="transparent", width=10, height=32)
        self.frames = [self.stage, self.bottom, self.footer]
        self.refresh(force=True)

    def _build_keyboard(self, parent):
        s = self.app.scale
        k, g = self.KEY_W * s, self.GAP * s
        unit, pad = k + g, 6 * s
        width = keys.WIDTH * unit - g + 2 * pad
        height = 5 * unit - g + 2 * pad
        self.canvas = tk.Canvas(parent, width=width, height=height, bg=STAGE,
                                highlightthickness=0)
        self.canvas.grid(row=2, column=0, padx=16, pady=(10, 18))
        self.key_items = {}
        for key, (x, y, w, h) in keys.POSITIONS.items():
            self._key(key, pad + x * unit, pad + y * unit, w * unit - g, h * unit - g, s)

    def _key(self, key, x, y, w, h, s):
        r, glow = 9 * s, 3 * s
        halo = self.canvas.create_polygon(
            rounded_points(x - glow, y - glow, x + w + glow, y + h + glow, r + glow),
            smooth=True, fill=STAGE, outline="")
        body = self.canvas.create_polygon(rounded_points(x, y, x + w, y + h, r), smooth=True,
                                          fill=KEY_OFF, outline="")
        label = self.canvas.create_text(x + w / 2, y + h / 2, text=keys.label(key),
                                        fill=KEY_TEXT, font=(FONT, 12, "bold"))
        self.key_items[key] = (halo, body, label)

    # ------------------------------------------------------------ devices

    @staticmethod
    def shows(out):
        return out.typing or not out.available

    def set_outputs(self, outputs):
        self.engine.set_outputs(outputs, set(self.settings["disabled_devices"]))

    def set_enabled(self, out, on):
        self.engine.set_enabled(out.id, on)

    def select(self, out):
        pass

    def device_state(self, out):
        """(dot color, error message or "") of a device row while running."""
        with self.engine.lock:
            for slot in self.engine.slots:
                if slot.kb.id == out.id:
                    if not slot.ok:
                        return BAD, slot.status
                    return DOTS.get(slot.status, FAINT), ""
        return FAINT, ""

    # ------------------------------------------------------------ running

    @property
    def running(self):
        return self.engine.running

    def start(self):
        if not self.live:
            return
        if not self._preloading:  # load every mode's model in the background
            self._preloading = True
            threading.Thread(target=self.models.preload, name="preload", daemon=True).start()
        hotkeys, self.hotkey_error = {}, ""
        try:
            hotkeys[parse_hotkey(self.settings["private_hotkey"])] = self.engine.toggle_private
        except ValueError as e:
            self.hotkey_error = str(e)
        self.engine.start()
        self.hook = KeyboardHook(self.engine.on_key, hotkeys)
        try:
            self.hook.start()
        except OSError as e:
            self.hotkey_error = str(e)

    def stop(self):
        if self.hook:
            self.hook.stop()
            self.hook = None
        self.engine.stop()
        self._save_learned()

    def pill(self):
        eng = self.engine
        if eng.private:
            return "Private", WARN
        if eng.secret:
            return "Password field", WARN
        if eng.idle:
            return "Idle", INFO
        lit = sum(s.status == "lit" for s in eng.slots)
        if lit:
            return f"Live  ·  {lit} keyboard{'s' if lit > 1 else ''}", GOOD
        if any(not s.ok for s in eng.slots):
            return "Device error", BAD
        return "Live  ·  no keyboard", WARN

    def message(self):
        msg = [self.hotkey_error] if self.hotkey_error else []
        if not self.engine.slots:
            msg.append("No per-key keyboard found. Start G HUB / Razer Synapse / SteelSeries GG "
                       "/ OpenRGB (SDK server), plug in the Model 100, then Scan.")
        return "   ".join(msg) or ("Green = best guess · yellow = 2nd · red = 3rd. "
                                   "Password fields are skipped automatically.")

    def tick(self):
        if self.engine.version != self.seen_version:
            self.refresh()
        if (self.settings["remember_words"] and self.running
                and time.monotonic() - self.saved_at > AUTOSAVE_S):
            self.saved_at = time.monotonic()
            threading.Thread(target=self._save_learned, daemon=True).start()

    def refresh(self, force=False):
        eng = self.engine
        with eng.lock:
            if eng.version == self.seen_version and not force:
                return
            self.seen_version = eng.version
            lit, preds, text = dict(eng.lit), list(eng.predictions), eng.text
            mode, reason, auto = eng.mode, eng.mode_reason, eng.auto
            secret, private = eng.secret, eng.private
            learned = self.models.stats()
        running = self.running

        colors = [hex_color(c) for c in self.settings["key_colors"]]
        for key, (halo, body, label) in self.key_items.items():
            rank = lit.get(key)
            if rank is None:
                self.canvas.itemconfig(halo, fill=STAGE)
                self.canvas.itemconfig(body, fill=KEY_OFF)
                self.canvas.itemconfig(label, fill=KEY_TEXT)
            else:
                self.canvas.itemconfig(halo, fill=blend(colors[rank], STAGE, 0.35))
                self.canvas.itemconfig(body, fill=colors[rank])
                self.canvas.itemconfig(label, fill="#0b0d10")
        for i, chip in enumerate(self.chips):
            ch = preds[i] if i < len(preds) and running else ""
            chip.configure(text={" ": "␣", "\n": "⏎"}.get(ch, ch.upper()),
                           fg_color=colors[i] if ch else KEY_OFF)

        name = self.mode_names.get(mode, mode)
        why = f"Using {name}" + (f"  ·  {reason}" if auto and reason else "")
        self.mode_label.configure(text=why if len(why) <= 52 else why[:51] + "…")

        if private:
            self.context.configure(text=f"Private mode - nothing is read until you press "
                                        f"{self.hotkey_label} again", text_color=WARN,
                                   font=(FONT, 14, "bold"))
        elif secret:
            self.context.configure(text="Password field - not recorded, keys dark",
                                   text_color=WARN, font=(FONT, 14, "bold"))
        elif not running:
            self.context.configure(text="Press Start - then type anywhere", text_color=MUTED,
                                   font=(FONT, 14))
        elif not self.settings["show_text"]:
            self.context.configure(text="typing hidden", text_color=MUTED, font=(FONT, 14))
        else:
            shown = text[-40:].replace("\n", "⏎")
            self.context.configure(text=(shown or "start typing anywhere") + "▏",
                                   text_color=TEXT if shown else MUTED, font=(MONO, 17))

        self.private_btn.configure(
            text=f"{'End private mode' if private else 'Private mode'}   {self.hotkey_label}",
            fg_color=blend(WARN, CARD, 0.3) if private else FIELD)

        lines = [f"{n}:  {s}" for n, s in learned] or ["Nothing yet - it learns as you type."]
        if not self.settings["remember_words"]:
            lines.append("Forgotten when you close.")
        self.learned_label.configure(text="\n".join(lines))

    # ------------------------------------------------------------- actions

    def toggle_private(self):
        if self.running:
            self.engine.toggle_private()  # in order with the keys being processed
        else:
            with self.engine.lock:
                self.engine._set_private(not self.engine.private)
                self.engine.version += 1

    def choose_mode(self, label):
        self.engine.set_mode(self.mode_choices[label])

    def forget(self):
        if not messagebox.askyesno("Forget learned words",
                                   "Forget everything Hotk33 has learned from your typing, "
                                   "in every mode?", parent=self.app.root):
            return
        with self.engine.lock:
            self.models.forget()
            self.engine.version += 1

    def toggle_remember(self):
        on = bool(self.remember.get())
        self.settings["remember_words"] = on
        self.models.learned_path = self.learned_path if on else None
        if not on and self.learned_path.exists():
            self.learned_path.unlink()
        self.engine.version += 1

    def toggle_show_text(self):
        self.settings["show_text"] = bool(self.show_text.get())
        self.engine.version += 1

    def _private_sound(self, on):
        if not self.settings.get("hotkey_sound", True):
            return
        import winsound
        tones = (660, 990) if on else (990, 660)
        threading.Thread(target=lambda: [winsound.Beep(f, 70) for f in tones],
                         daemon=True).start()

    def _save_learned(self):
        with self.engine.lock:
            try:
                self.models.save()
            except OSError:
                pass

    def close(self):
        self.stop()
