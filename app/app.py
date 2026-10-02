"""Hotk33: RGB lighting that reacts to your music (Music mode), or that shows
the keys you're most likely to type next (Typing mode). The main window."""

import copy
import ctypes
import json
import os
import shutil
import sys
import threading
from pathlib import Path

import customtkinter as ctk

from devices import scan_all
from music import page as music_page
from paint import page as paint_page
from predictive import page as typing_page
from styles import page as styles_page
from version import __version__
from widgets import (ACCENT, ACCENT_HOVER, BAD, BG, CARD, CARD_BORDER, FAINT, FIELD, FIELD_HOVER,
                     FONT, FONT_DISPLAY, MUTED, TEXT, TRACK, WARN, app_icon, blend)

HERE = Path(__file__).resolve().parent
APPDATA = Path(os.environ.get("APPDATA", Path.home()))
DATA_DIR = APPDATA / "Hotk33"
SETTINGS_FILE = DATA_DIR / "settings.json"
LEARNED_FILE = DATA_DIR / "learned.json"
LAYOUTS_FILE = DATA_DIR / "paint_layouts.json"
CRASH_LOG = DATA_DIR / "crash.log"
ICON_FILE = DATA_DIR / "icon.ico"
MUSIC, TYPING, PAINT, STYLES = "Music", "Typing", "Paint", "Styles"
# Typing mode is switched off for now: it crashed when opened in 2.1.0. Its
# code stays (app/predictive/) so it can come back once that's fixed.
TYPING_ENABLED = False
MODES = [MUSIC] + ([TYPING] if TYPING_ENABLED else []) + [PAINT, STYLES]
TAGLINES = {MUSIC: "Lighting that reacts to your music",
            TYPING: "Lights up the keys you'll type next",
            PAINT: "Paint your own lighting, key by key",
            STYLES: "Ready-made lighting styles, and your own"}
DEFAULTS = {
    "page": MUSIC,
    "running": False,         # was lighting when the app was closed: start again
    "disabled_devices": [],   # ids of lighting devices switched off
    "preview_device": "",
    **music_page.DEFAULTS,
    **typing_page.DEFAULTS,
    **paint_page.DEFAULTS,
    **styles_page.DEFAULTS,
}

# Settings of the two apps Hotk33 replaces, imported on first start.
OLD_MUSIC = [APPDATA / "MusicVisualizer" / "settings.json", HERE / "settings.json"]
OLD_TYPING = APPDATA / "PredictiveKeyLights"
OLD_KEYS = {"device": "audio_device", "mode": "typing_mode", "colors": "key_colors"}


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def import_old_settings():
    """Settings from Music Visualizer and Predictive Key Lights, if found."""
    found, disabled = {}, set()
    music = next((s for s in map(_read_json, OLD_MUSIC) if isinstance(s, dict)), None)
    typing = _read_json(OLD_TYPING / "settings.json")
    for old in (music, typing):
        if not isinstance(old, dict):
            continue
        disabled.update(old.pop("disabled_devices", []))
        found.update({OLD_KEYS.get(k, k): v for k, v in old.items() if k != "port"})
    if isinstance(typing, dict) and not music and TYPING_ENABLED:
        found["page"] = TYPING
    if disabled:
        found["disabled_devices"] = sorted(disabled)
    learned = OLD_TYPING / "learned.json"
    if learned.exists() and not LEARNED_FILE.exists():
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy(learned, LEARNED_FILE)
        except OSError:
            pass
    return found


def load_settings():
    settings = copy.deepcopy(DEFAULTS)
    saved = _read_json(SETTINGS_FILE)
    saved = saved if isinstance(saved, dict) else import_old_settings()
    if "custom_color" in saved and "custom_colors" not in saved:  # one color before 2.0
        saved["custom_colors"] = [saved["custom_color"]]
    settings.update({k: v for k, v in saved.items() if k in DEFAULTS})
    if settings["page"] not in MODES:
        settings["page"] = MUSIC
    music_page.check_settings(settings)
    paint_page.check_settings(settings)
    styles_page.check_settings(settings)
    return settings


def save_settings(settings):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)
    except OSError:
        pass


class App:
    def __init__(self, root, live=True):
        """live=False (screenshots): no keyboard hook, no lighting, no device scan."""
        self.root = root
        self.settings = load_settings()
        self.scale = ctk.ScalingTracker.get_window_scaling(root)
        self.outputs = []       # every device found by the last scan
        self.problems = []
        self.rows = {}          # device id -> widgets of its row in the list
        self.selected = None    # device shown in the Music preview
        self._scan_result = None
        self._scanning = False
        self._resume = False    # restart lighting once the scan is done
        self._shown = None

        root.title(f"Hotk33 {__version__}")
        root.configure(fg_color=BG)
        root.geometry("1180x900")
        root.minsize(1040, 820)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._set_icon()

        self.fonts = {
            "title": ctk.CTkFont(FONT_DISPLAY, 22, "bold"),
            "body": ctk.CTkFont(FONT, 13),
            "bold": ctk.CTkFont(FONT, 13, "bold"),
            "small": ctk.CTkFont(FONT, 12),
            "section": ctk.CTkFont(FONT, 11, "bold"),
        }

        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(1, weight=1)
        self._build_header()
        stage, bottom, footer = self._build_body()
        self.pages = {
            MUSIC: music_page.MusicPage(self, stage, bottom, footer),
            PAINT: paint_page.PaintPage(self, stage, bottom, footer, LAYOUTS_FILE),
        }
        self.pages[STYLES] = styles_page.StylesPage(self, stage, bottom, footer,
                                                    self.pages[PAINT].store)
        if TYPING_ENABLED:
            self.pages[TYPING] = typing_page.TypingPage(self, stage, bottom, footer,
                                                        LEARNED_FILE, live)
        self.page = self.pages[self.settings["page"]]
        self.mode_btn.set(self.page.name)
        self._show_page()
        self._update_run_state()
        if live:
            self._resume = self.settings["running"]
            self.scan()
        self.tick()

    # ------------------------------------------------------------ helpers

    def _set_icon(self):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            if not ICON_FILE.exists():
                app_icon().save(ICON_FILE, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
            self.root.iconbitmap(str(ICON_FILE))
        except Exception:  # noqa: BLE001 - no icon (or no .ico support off Windows)
            pass

    def card(self, parent, title=None, **grid):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14, border_width=1,
                            border_color=CARD_BORDER)
        card.grid(**grid)
        card.grid_columnconfigure(0, weight=1)
        if title:
            self.section(card, title).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 8))
        return card

    def section(self, parent, title):
        return ctk.CTkLabel(parent, text=title.upper(), font=self.fonts["section"],
                            text_color=MUTED, height=18)

    def small_button(self, parent, text, command, width=64):
        return ctk.CTkButton(parent, text=text, font=self.fonts["small"], width=width, height=26,
                             corner_radius=8, fg_color=FIELD, hover_color=FIELD_HOVER,
                             text_color=TEXT, command=command)

    def switch(self, parent, text, command):
        return ctk.CTkSwitch(parent, text=text, font=self.fonts["body"], text_color=TEXT,
                             progress_color=ACCENT, fg_color=TRACK, button_color="#f4f4f8",
                             button_hover_color="#ffffff", command=command)

    # ------------------------------------------------------------ layout

    def _build_header(self):
        hdr = ctk.CTkFrame(self.root, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 14))
        hdr.grid_columnconfigure(2, weight=1)

        logo = ctk.CTkImage(app_icon(128), size=(42, 42))
        ctk.CTkLabel(hdr, image=logo, text="").grid(row=0, column=0, rowspan=2, padx=(0, 14))
        ctk.CTkLabel(hdr, text="Hotk33", font=self.fonts["title"], text_color=TEXT,
                     height=28).grid(row=0, column=1, sticky="sw")
        self.tagline = ctk.CTkLabel(hdr, text="", font=self.fonts["small"], text_color=MUTED,
                                    height=18)
        self.tagline.grid(row=1, column=1, sticky="nw")

        self.mode_btn = ctk.CTkSegmentedButton(
            hdr, values=MODES, command=self.switch_page, font=self.fonts["bold"],
            width=95 * len(MODES), height=36, corner_radius=10, fg_color=FIELD,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER, unselected_color=FIELD,
            unselected_hover_color=FIELD_HOVER, text_color=TEXT)
        self.mode_btn.grid(row=0, column=2, rowspan=2, padx=20)

        self.pill = ctk.CTkLabel(hdr, text="", font=self.fonts["bold"], corner_radius=15,
                                 height=30)
        self.pill.grid(row=0, column=3, rowspan=2, padx=14)
        self._pill_state = None
        self.start_btn = ctk.CTkButton(hdr, text="Start", font=self.fonts["bold"], width=120,
                                       height=40, corner_radius=12, command=self.toggle)
        self.start_btn.grid(row=0, column=4, rowspan=2)

    def _build_body(self):
        """The shared device list, plus the containers each page fills:
        (stage, bottom, footer)."""
        main = ctk.CTkFrame(self.root, fg_color="transparent")
        main.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 12))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=1)
        stage = ctk.CTkFrame(main, fg_color="transparent")
        stage.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        stage.grid_columnconfigure(0, weight=1)
        stage.grid_rowconfigure(0, weight=1)

        card = self.card(main, row=0, column=1, sticky="nsew")
        card.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=(18, 12), pady=(12, 4))
        head.grid_columnconfigure(0, weight=1)
        self.dev_title = self.section(head, "Devices")
        self.dev_title.grid(row=0, column=0, sticky="w")
        self.scan_btn = self.small_button(head, "Scan", self.scan)
        self.scan_btn.grid(row=0, column=1, sticky="e")
        self.dev_list = ctk.CTkScrollableFrame(
            card, fg_color="transparent", width=290, height=10,
            scrollbar_button_color=FIELD, scrollbar_button_hover_color=FIELD_HOVER)
        self.dev_list.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 10))
        self.dev_list.grid_columnconfigure(0, weight=1)

        bottom = ctk.CTkFrame(self.root, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 12))
        bottom.grid_columnconfigure(0, weight=1)

        foot = ctk.CTkFrame(self.root, fg_color="transparent")
        foot.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 16))
        foot.grid_columnconfigure(1, weight=1)
        footer = ctk.CTkFrame(foot, fg_color="transparent")
        footer.grid(row=0, column=0, sticky="w")
        self.detail = ctk.CTkLabel(foot, text="", font=self.fonts["small"], text_color=FAINT,
                                   anchor="e", justify="right", wraplength=640)
        self.detail.grid(row=0, column=1, sticky="e", padx=(16, 2))
        return stage, bottom, footer

    def _show_page(self):
        for page in self.pages.values():
            for frame in page.frames:
                frame.grid_remove()
        stage, bottom, footer = self.page.frames
        stage.grid(row=0, column=0, sticky="nsew")
        bottom.grid(row=0, column=0, sticky="ew")
        footer.grid(row=0, column=0, sticky="w")
        self.tagline.configure(text=TAGLINES[self.page.name])
        self.dev_title.configure(text="KEYBOARDS" if self.page.name == TYPING else "DEVICES")
        if hasattr(self.page, "on_show"):
            self.page.on_show()
        self._show_devices()

    # ------------------------------------------------------------ pages

    def switch_page(self, name):
        if name == self.page.name:
            return
        running = self.page.running
        if running:  # one mode at a time: they'd fight over the same devices
            self.page.stop()
        self.page = self.pages[name]
        self.settings["page"] = name
        self._show_page()
        if running:
            self.page.start()
        self._update_run_state()

    def toggle(self):
        if self._scanning and not self.page.running:  # start once the devices are known
            self._resume = not self._resume
            self._set_pill("Starting after the scan" if self._resume else "Stopped", MUTED)
            return
        if self.page.running:
            self.page.stop()
        else:
            self.page.start()
        self.settings["running"] = self.page.running
        self._update_run_state()

    def stopped_by_page(self):
        """A page stopped on its own (e.g. the audio device failed)."""
        self.settings["running"] = False
        self._update_run_state()

    def _update_run_state(self):
        if self.page.running:
            self.start_btn.configure(text="Stop", fg_color=FIELD, hover_color=FIELD_HOVER,
                                     text_color=TEXT)
        else:
            self.start_btn.configure(text="Start", fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                     text_color="#ffffff")
            self._set_pill("Stopped", MUTED)

    def _set_pill(self, text, color):
        if (text, color) != self._pill_state:
            self._pill_state = (text, color)
            bg = FIELD if color == MUTED else blend(color, BG, 0.16)
            self.pill.configure(text=f"   ●  {text}   ", text_color=color, fg_color=bg)

    # ------------------------------------------------------------ devices

    def scan(self):
        if self._scanning:
            return
        self._scanning = True
        if self.page.running:  # devices get re-created, so stop lighting meanwhile
            self._resume = True
            self.page.stop()
            self._update_run_state()
        self.scan_btn.configure(text="Scanning", state="disabled")
        threading.Thread(target=lambda: setattr(self, "_scan_result", scan_all()),
                         daemon=True).start()

    def _apply_scan(self, outputs, problems):
        self._scanning = False
        self.scan_btn.configure(text="Scan", state="normal")
        self.outputs, self.problems = outputs, problems
        for page in self.pages.values():
            page.set_outputs(outputs)
        wanted = [o for o in outputs if o.id == self.settings["preview_device"] and o.music]
        enabled = [o for o in outputs if o.music and o.id not in self.settings["disabled_devices"]]
        self.selected = (wanted or enabled or [o for o in outputs if o.music] or [None])[0]
        self._show_devices()
        if self._resume:
            self._resume = False
            self.page.start()
            self.settings["running"] = self.page.running
            self._update_run_state()

    def _show_devices(self):
        for child in self.dev_list.winfo_children():
            child.destroy()
        self.rows = {}
        shown = [o for o in self.outputs if self.page.shows(o)]
        if not shown:
            text = ("Scanning..." if self._scanning else
                    "No lighting devices found.\nSee the README for what each brand needs."
                    if self.page.name != TYPING else
                    "No per-key keyboards found.\nSee the README for what each brand needs.")
            ctk.CTkLabel(self.dev_list, text=text, font=self.fonts["small"], text_color=MUTED,
                         justify="left").grid(row=0, column=0, sticky="w", padx=12, pady=8)
        for i, out in enumerate(shown):
            self._device_row(out, i)
        self._select(self.selected)

    def _device_row(self, out, i):
        f = self.fonts
        row = ctk.CTkFrame(self.dev_list, fg_color="transparent", corner_radius=10)
        row.grid(row=i, column=0, sticky="ew", pady=2)
        row.grid_columnconfigure(1, weight=1)
        dot = ctk.CTkLabel(row, text="●", width=14, font=f["small"],
                           text_color=WARN if not out.available else FAINT)
        dot.grid(row=0, column=0, rowspan=2, padx=(10, 6))
        name = ctk.CTkLabel(row, text=out.name, font=f["bold"], text_color=TEXT, anchor="w",
                            justify="left", wraplength=190, height=18)
        name.grid(row=0, column=1, sticky="ew", pady=(8, 0))
        detail = ctk.CTkLabel(row, text=out.hint or out.detail, font=f["small"],
                              text_color=WARN if not out.available else MUTED,
                              anchor="w", justify="left", wraplength=190, height=16)
        detail.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        switch = ctk.CTkSwitch(row, text="", width=44, progress_color=ACCENT, fg_color=TRACK,
                               button_color="#f4f4f8", button_hover_color="#ffffff")
        if not out.available:
            switch.configure(state="disabled", button_color=MUTED)
        else:
            switch.configure(command=lambda: self._on_toggle_device(out, switch.get()))
            if out.id not in self.settings["disabled_devices"]:
                switch.select()
        switch.grid(row=0, column=2, rowspan=2, padx=(4, 6))
        for w in (row, dot, name, detail):
            w.bind("<Button-1>", lambda e, o=out: self._select(o))
        self.rows[out.id] = {"frame": row, "dot": dot, "detail": detail, "out": out,
                             "shown": None}

    def _select(self, out):
        if out is not None and not out.music:
            return  # Music previews the selected device, Paint paints it
        self.selected = out
        if out:
            self.settings["preview_device"] = out.id
        for dev_id, r in self.rows.items():
            on = self.page.name != TYPING and out is not None and dev_id == out.id
            r["frame"].configure(fg_color=FIELD if on else "transparent")
        self.pages[MUSIC].select(out)
        self.pages[PAINT].select(out)
        self.pages[STYLES].select(out)

    def _on_toggle_device(self, out, on):
        disabled = self.settings["disabled_devices"]
        if on and out.id in disabled:
            disabled.remove(out.id)
        elif not on and out.id not in disabled:
            disabled.append(out.id)
        for page in self.pages.values():
            page.set_enabled(out, on)

    def _update_rows(self):
        running = self.page.running
        for r in self.rows.values():
            out = r["out"]
            if not out.available:
                continue
            dot, error = self.page.device_state(out) if running else (FAINT, "")
            if out.id in self.settings["disabled_devices"]:
                dot, error = FAINT, ""
            shown = (dot, error)
            if r["shown"] != shown:
                r["shown"] = shown
                r["dot"].configure(text_color=dot)
                r["detail"].configure(text=error or out.detail,
                                      text_color=BAD if error else MUTED)

    # ------------------------------------------------------------ loop

    def tick(self):
        if self._scan_result is not None:
            result, self._scan_result = self._scan_result, None
            self._apply_scan(*result)
        self.page.tick()
        if self.page.running:
            self._set_pill(*self.page.pill())
        self._update_rows()
        detail = "   ".join(m for m in [self.page.message()] + self.problems if m)
        if detail != self._shown:
            self._shown = detail
            self.detail.configure(text=detail)
        self.root.after(33, self.tick)

    def on_close(self):
        for page in self.pages.values():
            page.close()
        save_settings(self.settings)
        self.root.destroy()


def single_instance():
    """False if Hotk33 is already running (two copies would fight over the lights)."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, "Local\\Hotk33")
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def log_crashes(root=None):
    """Writes errors that would otherwise vanish (the packaged app has no
    console) to crash.log: Python errors on any thread or in the window, and
    hard crashes inside Windows / driver code. Returns the open log file."""
    import datetime
    import faulthandler
    import traceback
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log = open(CRASH_LOG, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - kept open
    except OSError:
        return None

    def write(kind, exc_type, exc, tb):
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        log.write(f"\n--- {stamp}  Hotk33 {__version__}  {kind}\n")
        log.write("".join(traceback.format_exception(exc_type, exc, tb)))

    faulthandler.enable(log)  # hard crashes (access violations in DLLs, ...)
    sys.excepthook = lambda t, e, tb: write("error", t, e, tb)
    threading.excepthook = lambda a: write(f"error in thread {a.thread.name if a.thread else ''}",
                                           a.exc_type, a.exc_value, a.exc_traceback)
    if root is not None:
        root.report_callback_exception = lambda t, e, tb: write("error in the window", t, e, tb)
    return log


def self_test():
    """Checks that this copy of Hotk33 (e.g. a release build) has everything it
    needs: every Typing model loads and the window builds. Lights nothing, reads
    no keys. Returns the process exit code."""
    from predictive.predict import Models
    try:
        models = Models(Path(typing_page.__file__).resolve().parent)
        for mode in models.index:
            models.get(mode).predict("the ")
        if len(models.index) < 2:
            raise RuntimeError("the coding / terminal models are missing")
        ctk.set_appearance_mode("dark")
        root = ctk.CTk()
        app = App(root, live=False)
        for name in app.pages:
            app.switch_page(name)
            root.update()
        root.destroy()
    except Exception:  # noqa: BLE001 - any failure fails the test
        import traceback
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "self-test.log").write_text(traceback.format_exc(), encoding="utf-8")
        return 1
    return 0


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    if not single_instance():
        ctypes.windll.user32.MessageBoxW(None, "Hotk33 is already running.", "Hotk33", 0x40)
        return
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    log_crashes(root)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
    # Everything is saved and released by now. Skip interpreter shutdown: unloading
    # the G HUB SDK DLL can deadlock there and leave the process hanging.
    sys.stdout.flush()
    os._exit(0)
