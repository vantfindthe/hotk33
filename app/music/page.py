"""Music mode's part of the window: device preview, effect, colors, levels,
the band equalizer and the audio device."""

from tkinter import colorchooser

import customtkinter as ctk
import numpy as np

from widgets import (ACCENT, ACCENT_HOVER, BAD, CARD, FAINT, FIELD, FIELD_HOVER, FONT, GOOD,
                     INFO, MUTED, STAGE, CARD_BORDER, TEXT, TRACK, WARN, DevicePreview,
                     gradient_image)
from . import audio, effects
from .engine import CUSTOM, Engine, palette_for
from .equalizer import Equalizer

EQ_RANGE_DB = 24
DEFAULTS = {
    "effect": "Bars",
    "palette": "Rainbow",
    "custom_color": [0, 180, 255],
    "sensitivity": 50,
    "smoothing": 50,
    "brightness": 70,
    "fps": 50,
    "release_on_silence": True,
    "eq": [0] * audio.NUM_BANDS,
    "audio_device": "",
}
# Names used by earlier versions of the app.
LEGACY_EFFECTS = {"Spectrum bars": "Bars", "Mirrored spectrum": "Mirror",
                  "Spectrum glow": "Glow", "Beat pulse": "Pulse"}
# device (worker) state: dot color
DOTS = {"live": GOOD, "resting": INFO, "connecting": WARN, "error": BAD}


def check_settings(settings):
    """Repairs Music settings saved by older versions (or edited by hand)."""
    settings["effect"] = LEGACY_EFFECTS.get(settings["effect"], settings["effect"])
    if settings["effect"] not in effects.EFFECTS:
        settings["effect"] = DEFAULTS["effect"]
    if settings["palette"] == "Custom color":
        settings["palette"] = CUSTOM
    if settings["palette"] not in effects.PALETTES and settings["palette"] != CUSTOM:
        settings["palette"] = DEFAULTS["palette"]
    if len(settings["eq"]) != audio.NUM_BANDS:
        settings["eq"] = list(DEFAULTS["eq"])


class MusicPage:
    name = "Music"

    def __init__(self, app, stage, bottom, footer):
        self.app = app
        self.settings = app.settings
        self.engine = None
        self.error = ""
        self.devices = []
        self.outputs = []
        self.preview_output = None
        f = app.fonts

        # stage: the selected device, lit live
        self.stage = ctk.CTkFrame(stage, fg_color=STAGE, corner_radius=16, border_width=1,
                                  border_color=CARD_BORDER)
        self.stage.grid_columnconfigure(0, weight=1)
        self.stage.grid_rowconfigure(0, weight=1)
        self.preview = DevicePreview(self.stage, scale=app.scale, height=int(240 * app.scale))
        self.preview.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        # bottom: effect + colors, levels, equalizer
        self.bottom = ctk.CTkFrame(bottom, fg_color="transparent")
        self.bottom.grid_columnconfigure(0, weight=1)
        row = ctk.CTkFrame(self.bottom, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        row.grid_columnconfigure(0, weight=3, uniform="controls")
        row.grid_columnconfigure(1, weight=2, uniform="controls")

        look = app.card(row, "Effect", row=0, column=0, sticky="nsew", padx=(0, 12))
        self.effect_btn = ctk.CTkSegmentedButton(
            look, values=list(effects.EFFECTS), command=self._on_effect, font=f["body"],
            height=36, corner_radius=10, fg_color=FIELD, selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER, unselected_color=FIELD,
            unselected_hover_color=FIELD_HOVER, text_color=TEXT)
        self.effect_btn.set(self.settings["effect"])
        self.effect_btn.grid(row=1, column=0, sticky="ew", padx=18)
        self.effect_desc = ctk.CTkLabel(look, text="", font=f["small"], text_color=MUTED,
                                        anchor="w", height=22)
        self.effect_desc.grid(row=2, column=0, sticky="ew", padx=20, pady=(6, 0))
        self._update_effect_desc()

        app.section(look, "Colors").grid(row=3, column=0, sticky="w", padx=18, pady=(12, 6))
        chips = ctk.CTkFrame(look, fg_color="transparent")
        chips.grid(row=4, column=0, sticky="w", padx=12, pady=(0, 14))
        self.chips = {}
        for i, name in enumerate(list(effects.PALETTES) + [CUSTOM]):
            chip = ctk.CTkButton(chips, text=name, compound="top", font=f["small"],
                                 width=64, height=60, corner_radius=10, border_width=2,
                                 fg_color="transparent", hover_color=FIELD_HOVER,
                                 text_color=TEXT, border_spacing=4,
                                 command=lambda n=name: self._on_palette(n))
            chip.grid(row=0, column=i, padx=2)
            self.chips[name] = chip
        self._update_chip_images()

        levels = app.card(row, "Levels", row=0, column=1, sticky="nsew")
        grid = ctk.CTkFrame(levels, fg_color="transparent")
        grid.grid(row=1, column=0, sticky="ew", padx=18)
        grid.grid_columnconfigure(1, weight=1)
        for r, (key, label, lo, hi, unit) in enumerate([
                ("sensitivity", "Sensitivity", 0, 100, "%"),
                ("smoothing", "Smoothing", 0, 100, "%"),
                ("brightness", "Brightness", 5, 100, "%"),
                ("fps", "Frame rate", 10, 60, " fps")]):
            ctk.CTkLabel(grid, text=label, font=f["body"], text_color=TEXT, anchor="w",
                         width=92).grid(row=r, column=0, sticky="w", pady=3)
            value = ctk.CTkLabel(grid, text=f"{self.settings[key]}{unit}", font=f["bold"],
                                 text_color=TEXT, anchor="e", width=58)
            value.grid(row=r, column=2, sticky="e")
            slider = ctk.CTkSlider(
                grid, from_=lo, to=hi, number_of_steps=hi - lo, height=18, fg_color=TRACK,
                progress_color=ACCENT, button_color="#f4f4f8", button_hover_color="#ffffff",
                command=lambda v, k=key, lbl=value, u=unit: self._on_level(k, v, lbl, u))
            slider.set(self.settings[key])
            slider.grid(row=r, column=1, sticky="ew", padx=10)
        self.release_switch = app.switch(levels, "Normal lighting when the music stops",
                                         self._on_release)
        if self.settings["release_on_silence"]:
            self.release_switch.select()
        self.release_switch.grid(row=2, column=0, sticky="w", padx=18, pady=(10, 14))

        card = app.card(self.bottom, row=1, column=0, sticky="ew")
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 0))
        head.grid_columnconfigure(1, weight=1)
        app.section(head, "Band sensitivity").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(head, text="Drag to boost or cut a band  ·  double-click to zero  ·  "
                                "scroll to fine-tune", font=f["small"], text_color=FAINT,
                     height=18).grid(row=0, column=1, sticky="w", padx=14)
        app.small_button(head, "Reset", self._reset_eq).grid(row=0, column=2, sticky="e")
        self.eq = Equalizer(card, self.settings["eq"], EQ_RANGE_DB, app.scale,
                            height=int(190 * app.scale))
        self.eq.grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 12))

        # footer: audio device
        self.footer = ctk.CTkFrame(footer, fg_color="transparent")
        ctk.CTkLabel(self.footer, text="Audio", font=f["small"], text_color=MUTED).grid(
            row=0, column=0, padx=(2, 8))
        self.dev_menu = ctk.CTkOptionMenu(
            self.footer, width=360, values=[""], font=f["body"], dropdown_font=f["body"],
            height=32, corner_radius=8, fg_color=FIELD, button_color=FIELD,
            button_hover_color=FIELD_HOVER, dropdown_fg_color=CARD,
            dropdown_hover_color=FIELD_HOVER, text_color=TEXT, dropdown_text_color=TEXT,
            dynamic_resizing=False, command=lambda _: self._restart())
        self.dev_menu.grid(row=0, column=1, padx=(0, 8))
        ctk.CTkButton(self.footer, text="⟳", font=ctk.CTkFont(FONT, 16), width=32, height=32,
                      corner_radius=8, fg_color=FIELD, hover_color=FIELD_HOVER, text_color=TEXT,
                      command=self.refresh_audio).grid(row=0, column=2)

        self.frames = [self.stage, self.bottom, self.footer]
        self._on_palette_changed()
        self._show_idle()
        self.refresh_audio()

    # ------------------------------------------------------------ devices

    @staticmethod
    def shows(out):
        return out.music or getattr(out, "in_music", False)

    def set_outputs(self, outputs):
        self.outputs = outputs

    def set_enabled(self, out, on):
        if self.engine:  # only this device starts/stops; the others keep streaming
            if on:
                self.engine.add_output(out)
            else:
                self.engine.remove_output(out.id)

    def select(self, out):
        self.preview_output = out if out is not None and out.music else None
        if self.preview_output is None:
            self.preview.set_layout(None)
        else:
            self.preview.set_layout(out.layout, out.name)
        if self.engine:
            self.engine.preview = self.preview_output

    def device_state(self, out):
        """(dot color, error message or "") of a device row while running."""
        if self.engine:
            for w in self.engine.workers:
                if w.output.id == out.id:
                    return DOTS[w.state], w.status if w.state == "error" else ""
        return FAINT, ""

    # ------------------------------------------------------------ events

    def _on_effect(self, name):
        self.settings["effect"] = name
        self._update_effect_desc()

    def _update_effect_desc(self):
        self.effect_desc.configure(text=effects.EFFECTS[self.settings["effect"]].__doc__.strip())

    def _on_palette(self, name):
        if name == CUSTOM:
            r, g, b = self.settings["custom_color"]
            rgb, _ = colorchooser.askcolor(color=f"#{r:02x}{g:02x}{b:02x}", parent=self.app.root,
                                           title="Pick a color")
            if rgb:
                self.settings["custom_color"] = [int(c) for c in rgb]
                self._update_chip_images()
        self.settings["palette"] = name
        self._on_palette_changed()

    def _on_palette_changed(self):
        for name, chip in self.chips.items():
            chip.configure(border_color=ACCENT if name == self.settings["palette"] else CARD)
        palette, _ = palette_for(self.settings)
        self.band_colors = palette(np.linspace(0, 1, audio.NUM_BANDS))

    def _update_chip_images(self):
        for name, chip in self.chips.items():
            if name == CUSTOM:
                colors = np.array([self.settings["custom_color"]] * 2) / 255
            else:
                colors = effects.PALETTES[name](np.linspace(0, 1, 32))
            chip.configure(image=ctk.CTkImage(gradient_image(colors, (128, 48), 12),
                                              size=(50, 20)))

    def _on_level(self, key, value, label, unit):
        self.settings[key] = int(round(value))
        label.configure(text=f"{self.settings[key]}{unit}")

    def _on_release(self):
        self.settings["release_on_silence"] = bool(self.release_switch.get())

    def _reset_eq(self):
        self.settings["eq"][:] = [0] * audio.NUM_BANDS
        self.eq.redraw()

    def refresh_audio(self):
        try:
            self.devices = audio.list_devices()
        except OSError:
            self.devices = []
        names = [d[0] for d in self.devices] or ["No audio devices found"]
        self.dev_menu.configure(values=names)
        match = [d[0] for d in self.devices if d[0] == self.settings["audio_device"]]
        self.dev_menu.set(match[0] if match else names[0])

    # ------------------------------------------------------------ running

    @property
    def running(self):
        return self.engine is not None

    def _restart(self):
        if self.engine:  # pick up the changed audio device
            self.stop()
            self.start()

    def start(self):
        device = dict(self.devices).get(self.dev_menu.get())
        if device is None:
            self.error = "Pick an audio device first."
            return
        self.error = ""
        self.settings["audio_device"] = self.dev_menu.get()
        enabled = [o for o in self.outputs
                   if o.music and o.id not in self.settings["disabled_devices"]]
        self.engine = Engine(enabled, device, self.settings)
        self.engine.preview = self.preview_output
        self.engine.start()

    def stop(self):
        if self.engine:
            self.engine.stop()
            self.engine.join(timeout=3)
            self.engine = None
        self._show_idle()

    def _show_idle(self):
        self.preview.show(np.zeros_like(self.preview.colors))
        self.eq.set_levels(np.zeros(audio.NUM_BANDS), self.band_colors)

    def pill(self):
        """(text, color) for the status pill while running."""
        eng = self.engine
        ws = eng.workers
        live = sum(w.state == "live" for w in ws)
        if not ws:
            return f"Preview only  ·  {eng.fps} fps", WARN
        if live:
            return f"Live  ·  {live} device{'s' if live > 1 else ''}  ·  {eng.fps} fps", GOOD
        if all(w.state == "resting" for w in ws):
            return "Waiting for music", INFO
        if any(w.state == "connecting" for w in ws):
            return "Connecting", MUTED
        return "Device error", BAD

    def message(self):
        return self.error

    def tick(self):
        eng = self.engine
        if eng and not eng.is_alive():  # the engine gave up (audio error)
            self.engine = None
            self._show_idle()
            self.error = eng.error or ""
            self.app.stopped_by_page()
        elif eng:
            if self.preview_output is not None:
                self.preview.show(eng.frames.get(self.preview_output.id))
            self.eq.set_levels(eng.analyzer.bands, self.band_colors)

    def close(self):
        self.stop()
