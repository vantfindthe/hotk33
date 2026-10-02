"""Predictive Key Lights: lights up the keys you're most likely to type next.

Best guess green, second yellow, third red; every other key dark. Updates on
every key press, on every connected keyboard it can drive.
"""

import copy
import ctypes
import json
import os
import sys
import threading
import time
import tkinter as tk
import winsound
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

import keys
from engine import AUTO, Engine
from hook import KeyboardHook, format_hotkey, parse_hotkey
from modes import Detector
from predict import Models

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("APPDATA", HERE)) / "PredictiveKeyLights"
SETTINGS_PATH = DATA_DIR / "settings.json"
LEARNED_PATH = DATA_DIR / "learned.json"
AUTOSAVE_S = 60

DEFAULTS = {
    "mode": AUTO,                    # "auto" (by window) or a mode id
    "colors": [[0, 255, 0], [255, 190, 0], [255, 0, 0]],  # 1st, 2nd, 3rd guess
    "white_levels": [255, 80, 18],   # same, for white-only keyboards (G610)
    "remember_words": False,         # keep learned words between sessions
    "show_text": True,               # show the typed context in the window
    "private_hotkey": "ctrl+alt+p",  # stop reading keystrokes until pressed again
    "hotkey_sound": True,            # beep up / down when private mode switches
    "idle_release_s": 0,             # give keyboards their own lighting back after
                                     # this many idle seconds (0 = never)
    "disabled_devices": [],
}

# palette
BG = "#0e1014"
CARD = "#161920"
BORDER = "#242833"
KEY = "#232731"
KEY_TEXT = "#7c8496"
TEXT = "#e9ebf1"
MUTED = "#8a91a3"
ACCENT = "#5b8cff"
GOOD, WARN, BAD, IDLE = "#3ddc84", "#f2b33d", "#ff6b5e", "#5d6475"
FONT = "Segoe UI"
MONO = "Cascadia Mono"


def load_settings():
    settings = copy.deepcopy(DEFAULTS)
    try:
        settings.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError:
        pass


def hex_color(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def blend(fg, bg, amount):
    """fg over bg at `amount` (0..1), both '#rrggbb'."""
    f = [int(fg[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return hex_color([round(b[i] + (f[i] - b[i]) * amount) for i in range(3)])


def rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


def card(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14, border_width=1,
                        border_color=BORDER, **kw)


def heading(parent, text):
    return ctk.CTkLabel(parent, text=text.upper(), text_color=MUTED,
                        font=(FONT, 11, "bold"), anchor="w")


def pill(parent, text="", color=IDLE, **kw):
    return ctk.CTkLabel(parent, text=text, fg_color=blend(color, CARD, 0.18),
                        text_color=color, corner_radius=10, height=24,
                        font=(FONT, 12, "bold"), **kw)


class App:
    KEY_W = 46    # key size before DPI scaling
    GAP = 6

    def __init__(self, root, live=True):
        """live=False (screenshots): no keyboard hook, no lighting."""
        self.root = root
        self.settings = load_settings()
        learned = LEARNED_PATH if self.settings["remember_words"] else None
        self.models = Models(HERE, learned)
        self.mode_names = self.models.names()
        if self.settings["mode"] not in self.mode_names:
            self.settings["mode"] = AUTO
        self.engine = Engine(self.models, Detector(self.models.index), self.settings)
        self.engine.on_private = self._private_sound
        threading.Thread(target=self.models.preload, name="preload", daemon=True).start()
        self.seen_version = -1
        self.saved_at = time.monotonic()
        self.device_sig = None
        self.hotkey_label = format_hotkey(self.settings["private_hotkey"])
        self.hotkey_error = None

        root.title("Predictive Key Lights")
        root.configure(fg_color=BG)
        root.resizable(False, False)
        try:
            root.iconbitmap(default=str(HERE / "icon.ico"))
        except tk.TclError:
            pass
        self._build()

        hotkeys = {}
        try:
            hotkeys[parse_hotkey(self.settings["private_hotkey"])] = self.engine.toggle_private
        except ValueError as e:
            self.hotkey_error = str(e)
        self.hook = KeyboardHook(self.engine.on_key, hotkeys)
        if live:
            try:
                self.hook.start()
            except OSError as e:
                self.hotkey_error = str(e)
            threading.Thread(target=self.engine.run, name="sender", daemon=True).start()
            self.rescan()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self._poll()

    # ------------------------------------------------------------------ UI

    def _build(self):
        outer = ctk.CTkFrame(self.root, fg_color=BG)
        outer.pack(fill="both", expand=True, padx=18, pady=(14, 16))

        # header
        head = ctk.CTkFrame(outer, fg_color=BG)
        head.pack(fill="x", pady=(0, 12))
        dots = tk.Canvas(head, width=46, height=22, bg=BG, highlightthickness=0)
        for i, c in enumerate(self.settings["colors"]):
            dots.create_oval(2 + i * 15, 5, 14 + i * 15, 17, fill=hex_color(c), width=0)
        dots.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(head, text="Predictive Key Lights", text_color=TEXT,
                     font=(FONT, 20, "bold")).pack(side="left")
        ctk.CTkLabel(head, text="   lights the keys you'll type next", text_color=MUTED,
                     font=(FONT, 13)).pack(side="left", pady=(4, 0))
        self.state_pill = pill(head, " Live ", GOOD, width=110)
        self.state_pill.pack(side="right")

        # typing card: mode, context, predictions, keyboard
        typing = card(outer)
        typing.pack(fill="x")
        row = ctk.CTkFrame(typing, fg_color=CARD)
        row.pack(fill="x", padx=16, pady=(14, 4))
        heading(row, "Mode").pack(side="left", padx=(0, 10))
        self.mode_choices = {"Auto - follow the window I'm typing in": AUTO}
        self.mode_choices.update({name: m for m, name in self.mode_names.items()})
        current = next(label for label, m in self.mode_choices.items()
                       if m == self.settings["mode"])
        ctk.CTkOptionMenu(row, values=list(self.mode_choices), command=self.choose_mode,
                          variable=tk.StringVar(value=current), width=300, height=30,
                          fg_color=KEY, button_color=BORDER, button_hover_color="#2f3442",
                          dropdown_fg_color=CARD, dropdown_hover_color=KEY,
                          text_color=TEXT, font=(FONT, 13), dropdown_font=(FONT, 13),
                          corner_radius=8).pack(side="left")
        self.mode_label = ctk.CTkLabel(row, text="", text_color=MUTED, font=(FONT, 12),
                                       anchor="w")
        self.mode_label.pack(side="left", padx=12, fill="x", expand=True)

        row = ctk.CTkFrame(typing, fg_color=CARD)
        row.pack(fill="x", padx=16, pady=(6, 4))
        self.context = ctk.CTkLabel(row, text="", text_color=TEXT, font=(MONO, 17),
                                    anchor="w")
        self.context.pack(side="left", fill="x", expand=True)
        self.chips = []
        for i, caption in enumerate(("1st", "2nd", "3rd")):
            col = ctk.CTkFrame(row, fg_color=CARD)
            col.pack(side="left", padx=(8, 0))
            chip = ctk.CTkLabel(col, text="", width=46, height=40, corner_radius=10,
                                fg_color=KEY, text_color="#0b0d10", font=(FONT, 18, "bold"))
            chip.pack()
            ctk.CTkLabel(col, text=caption, text_color=MUTED, font=(FONT, 10),
                         height=14).pack()
            self.chips.append(chip)

        self._build_keyboard(typing)

        # devices + learning side by side
        lower = ctk.CTkFrame(outer, fg_color=BG)
        lower.pack(fill="x", pady=(12, 0))
        lower.grid_columnconfigure(0, weight=3, uniform="c")
        lower.grid_columnconfigure(1, weight=2, uniform="c")

        dev = card(lower)
        dev.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        top = ctk.CTkFrame(dev, fg_color=CARD)
        top.pack(fill="x", padx=16, pady=(12, 4))
        heading(top, "Keyboards").pack(side="left")
        ctk.CTkButton(top, text="Rescan", width=70, height=24, corner_radius=8,
                      fg_color=KEY, hover_color=BORDER, text_color=TEXT, font=(FONT, 12),
                      command=self.rescan).pack(side="right")
        self.dev_list = ctk.CTkFrame(dev, fg_color=CARD)
        self.dev_list.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        learn = card(lower)
        learn.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        heading(learn, "Learning").pack(fill="x", padx=16, pady=(12, 4))
        self.learned_label = ctk.CTkLabel(learn, text="", text_color=TEXT, font=(FONT, 12),
                                          anchor="w", justify="left", wraplength=290)
        self.learned_label.pack(fill="x", padx=16)
        self.remember = tk.BooleanVar(value=self.settings["remember_words"])
        self._switch(learn, "Remember between sessions", self.remember,
                     self.toggle_remember).pack(fill="x", padx=16, pady=(10, 4))
        ctk.CTkButton(learn, text="Forget everything learned", height=28, corner_radius=8,
                      fg_color=KEY, hover_color=blend(BAD, KEY, 0.35), text_color=TEXT,
                      font=(FONT, 12), command=self.forget
                      ).pack(fill="x", padx=16, pady=(4, 14))

        # controls
        bar = ctk.CTkFrame(outer, fg_color=BG)
        bar.pack(fill="x", pady=(12, 0))
        self.pause_btn = ctk.CTkButton(bar, text="Pause", width=100, height=34,
                                       corner_radius=10, fg_color=ACCENT,
                                       hover_color=blend(ACCENT, BG, 0.8),
                                       font=(FONT, 13, "bold"), command=self.toggle_pause)
        self.pause_btn.pack(side="left")
        self.private_btn = ctk.CTkButton(bar, text="", width=230, height=34, corner_radius=10,
                                         fg_color=KEY, hover_color=BORDER, text_color=TEXT,
                                         font=(FONT, 13), command=self.engine.toggle_private)
        self.private_btn.pack(side="left", padx=8)
        self.show_text = tk.BooleanVar(value=self.settings["show_text"])
        self._switch(bar, "Show typed text", self.show_text, self.toggle_show_text,
                     bg=BG).pack(side="right")
        self.status = ctk.CTkLabel(outer, text="", text_color=MUTED, font=(FONT, 11),
                                   anchor="w", justify="left")
        self.status.pack(fill="x", pady=(10, 0))

    @staticmethod
    def _switch(parent, text, var, command, bg=CARD):
        return ctk.CTkSwitch(parent, text=text, variable=var, command=command,
                             onvalue=True, offvalue=False, progress_color=ACCENT,
                             button_color=TEXT, button_hover_color="#ffffff", fg_color=BORDER,
                             text_color=TEXT, font=(FONT, 12), bg_color=bg)

    def _build_keyboard(self, parent):
        s = ctk.ScalingTracker.get_window_scaling(self.root)
        k, g = self.KEY_W * s, self.GAP * s
        pad = 6 * s
        width = 13 * (k + g) + 1.6 * k + 2 * pad
        height = 5 * (k + g) - g + 2 * pad
        self.canvas = tk.Canvas(parent, width=width, height=height, bg=CARD,
                                highlightthickness=0)
        self.canvas.pack(padx=16, pady=(6, 16))
        self.key_items = {}
        offsets = [0, 0.6, 0.85, 1.3]
        for r, row in enumerate(keys.ROWS):
            for c, key in enumerate(row):
                self._key(key, pad + (offsets[r] + c) * (k + g), pad + r * (k + g), k, k, s)
        self._key("space", pad + 3.3 * (k + g), pad + 4 * (k + g), 6.2 * k + 5 * g, k, s)
        enter_x = pad + (offsets[2] + len(keys.ROWS[2])) * (k + g)
        self._key("enter", enter_x, pad + 2 * (k + g), width - pad - enter_x, k, s)

    def _key(self, key, x, y, w, h, s):
        r = 9 * s
        glow = rounded_rect(self.canvas, x - 3 * s, y - 3 * s, x + w + 3 * s, y + h + 3 * s,
                            r + 3 * s, fill=CARD, outline="")
        body = rounded_rect(self.canvas, x, y, x + w, y + h, r, fill=KEY, outline="")
        label = self.canvas.create_text(x + w / 2, y + h / 2, text=keys.label(key),
                                        fill=KEY_TEXT, font=(FONT, 12, "bold"))
        self.key_items[key] = (glow, body, label)

    # ------------------------------------------------------------- refresh

    def _poll(self):
        if self.engine.version != self.seen_version:
            self._refresh()
        if self.remember.get() and time.monotonic() - self.saved_at > AUTOSAVE_S:
            self.saved_at = time.monotonic()
            threading.Thread(target=self._save_learned, daemon=True).start()
        self.root.after(30, self._poll)

    def _refresh(self):
        eng = self.engine
        with eng.lock:
            self.seen_version = eng.version
            lit, preds, text = dict(eng.lit), list(eng.predictions), eng.text
            mode, reason, auto = eng.mode, eng.mode_reason, eng.auto
            secret, private = eng.secret, eng.private
            paused, idle = eng.paused, eng.idle
            slots = [(s, s.kb.name, s.kb.detail, s.enabled and s.kb.available, s.status,
                      s.ok, s.kb.available) for s in eng.slots]
            problems = list(eng.problems)
            learned = self.models.stats()

        colors = [hex_color(c) for c in self.settings["colors"]]
        for key, (glow, body, label) in self.key_items.items():
            rank = lit.get(key)
            if rank is None:
                self.canvas.itemconfig(glow, fill=CARD)
                self.canvas.itemconfig(body, fill=KEY)
                self.canvas.itemconfig(label, fill=KEY_TEXT)
            else:
                self.canvas.itemconfig(glow, fill=blend(colors[rank], CARD, 0.35))
                self.canvas.itemconfig(body, fill=colors[rank])
                self.canvas.itemconfig(label, fill="#0b0d10")
        for i, chip in enumerate(self.chips):
            ch = preds[i] if i < len(preds) else ""
            chip.configure(text={" ": "␣", "\n": "⏎"}.get(ch, ch.upper()),
                           fg_color=colors[i] if ch else KEY)

        name = self.mode_names.get(mode, mode)
        self.mode_label.configure(
            text=f"Using {name}" + (f"  ·  {reason}" if auto and reason else ""))

        if private:
            self.context.configure(text=f"Private mode - nothing is read until you press "
                                        f"{self.hotkey_label} again", text_color=WARN,
                                   font=(FONT, 14, "bold"))
        elif secret:
            self.context.configure(text="Password field - not recorded, keys dark",
                                   text_color=WARN, font=(FONT, 14, "bold"))
        elif not self.show_text.get():
            self.context.configure(text="typing hidden", text_color=MUTED, font=(FONT, 14))
        else:
            shown = text[-40:].replace("\n", "⏎")
            self.context.configure(text=(shown or "start typing anywhere") + "▏",
                                   text_color=TEXT if shown else MUTED, font=(MONO, 17))

        if paused:
            self.state_pill.configure(text="Paused", text_color=IDLE,
                                      fg_color=blend(IDLE, BG, 0.25))
        elif private or secret:
            self.state_pill.configure(text="Private" if private else "Password",
                                      text_color=WARN, fg_color=blend(WARN, BG, 0.18))
        elif idle:
            self.state_pill.configure(text="Idle", text_color=IDLE,
                                      fg_color=blend(IDLE, BG, 0.25))
        else:
            self.state_pill.configure(text="● Live", text_color=GOOD,
                                      fg_color=blend(GOOD, BG, 0.15))
        self.pause_btn.configure(text="Resume" if paused else "Pause")
        self.private_btn.configure(
            text=f"{'End private mode' if private else 'Private mode'}   {self.hotkey_label}",
            fg_color=blend(WARN, BG, 0.3) if private else KEY)

        if learned:
            lines = [f"{n}:  {s}" for n, s in learned]
        else:
            lines = ["Nothing yet - it learns as you type."]
        if not self.remember.get():
            lines.append("Forgotten when you close.")
        self.learned_label.configure(text="\n".join(lines))

        sig = [(id(s), n, d, e, st, ok) for s, n, d, e, st, ok, _ in slots]
        if sig != self.device_sig:
            self.device_sig = sig
            self._show_devices(slots)

        msg = []
        if self.hotkey_error:
            msg.append(self.hotkey_error)
        if not slots:
            msg.append("No per-key keyboards found. Start G HUB / Razer Synapse / OpenRGB "
                       "(SDK server), plug in the Model 100, then Rescan.")
        msg += problems
        self.status.configure(text="\n".join(msg) or
                              "Green = best guess · yellow = 2nd · red = 3rd. "
                              "Password fields are skipped automatically.")

    def _show_devices(self, slots):
        for child in self.dev_list.winfo_children():
            child.destroy()
        for slot, name, detail, enabled, status, ok, available in slots:
            row = ctk.CTkFrame(self.dev_list, fg_color=KEY, corner_radius=10)
            row.pack(fill="x", pady=3)
            var = tk.BooleanVar(value=enabled)
            switch = ctk.CTkSwitch(row, text="", variable=var, width=40, progress_color=ACCENT,
                                   fg_color=BORDER, button_color=TEXT, bg_color=KEY,
                                   command=lambda s=slot, v=var: self.engine.set_enabled(
                                       s, v.get()))
            switch.pack(side="left", padx=(10, 0), pady=8)
            if not available:
                switch.configure(state="disabled", button_color=MUTED)
            text = ctk.CTkFrame(row, fg_color=KEY)
            text.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(text, text=name, text_color=TEXT, font=(FONT, 13, "bold"),
                         anchor="w", height=18).pack(fill="x")
            ctk.CTkLabel(text, text=detail, text_color=MUTED, font=(FONT, 11),
                         anchor="w", height=16).pack(fill="x")
            if not available:
                color, shown = WARN, "needs setup"
            else:
                color = GOOD if ok and status == "lit" else (BAD if not ok else IDLE)
                shown = status if len(status) < 34 else status[:32] + "…"
            badge = ctk.CTkLabel(row, text=f" {shown} ", text_color=color,
                                 fg_color=blend(color, KEY, 0.2), corner_radius=8,
                                 height=22, font=(FONT, 11, "bold"))
            badge.pack(side="right", padx=10)
            if not available or (not ok and len(status) >= 34):
                ctk.CTkLabel(text, text=status, text_color=color, font=(FONT, 11),
                             anchor="w", justify="left", wraplength=330
                             ).pack(fill="x", pady=(0, 6))
        if not slots:
            ctk.CTkLabel(self.dev_list, text="None found yet", text_color=MUTED,
                         font=(FONT, 12), anchor="w").pack(fill="x")

    # ------------------------------------------------------------- actions

    def rescan(self):
        threading.Thread(target=self.engine.scan, daemon=True).start()

    def choose_mode(self, label):
        self.engine.set_mode(self.mode_choices[label])
        save_settings(self.settings)

    def toggle_pause(self):
        self.engine.set_paused(not self.engine.paused)

    def forget(self):
        if not messagebox.askyesno("Forget learned words",
                                   "Forget everything Predictive Key Lights has learned "
                                   "from your typing, in every mode?", parent=self.root):
            return
        with self.engine.lock:
            self.models.forget()
            self.engine.version += 1

    def toggle_remember(self):
        on = self.remember.get()
        self.settings["remember_words"] = on
        self.models.learned_path = LEARNED_PATH if on else None
        if not on and LEARNED_PATH.exists():
            LEARNED_PATH.unlink()
        save_settings(self.settings)
        self.engine.version += 1

    def toggle_show_text(self):
        self.settings["show_text"] = self.show_text.get()
        save_settings(self.settings)
        self.engine.version += 1

    def _private_sound(self, on):
        if self.settings.get("hotkey_sound", True):
            tones = (660, 990) if on else (990, 660)
            threading.Thread(target=lambda: [winsound.Beep(f, 70) for f in tones],
                             daemon=True).start()

    def _save_learned(self):
        with self.engine.lock:
            try:
                self.models.save()
            except OSError:
                pass

    def quit(self):
        self.hook.stop()
        self.engine.stop()
        self._save_learned()
        save_settings(self.settings)
        self.root.destroy()


def single_instance():
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, "Local\\PredictiveKeyLights")
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def main():
    if not single_instance():
        ctypes.windll.user32.MessageBoxW(None, "Predictive Key Lights is already running.",
                                         "Predictive Key Lights", 0x40)
        return
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
    # Everything is saved and released by now. Skip interpreter shutdown: unloading
    # the G HUB SDK DLL can deadlock there and leave the process hanging.
    sys.stdout.flush()
    os._exit(0)
