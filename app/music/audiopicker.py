"""Picks the audio to follow: what's playing (speakers, via WASAPI loopback)
or an input (microphone / line-in). Shared by Music mode and Paint mode's
audio reaction; the choice is kept in settings["audio_source"] and
settings["audio_device"]."""

import customtkinter as ctk

from widgets import ACCENT, ACCENT_HOVER, CARD, FIELD, FIELD_HOVER, FONT, MUTED, TEXT
from . import audio

SPEAKERS, MIC = "Speakers", "Microphone"
_PREFIX = {SPEAKERS: "Speakers: ", MIC: "Mic: "}


class AudioPicker(ctk.CTkFrame):
    def __init__(self, parent, app, on_change=None):
        super().__init__(parent, fg_color="transparent")
        self.settings = app.settings
        self.on_change = on_change
        self.devices = []  # (label, device index) of the chosen source
        f = app.fonts
        ctk.CTkLabel(self, text="Audio", font=f["small"], text_color=MUTED).grid(
            row=0, column=0, padx=(2, 8))
        self.source = ctk.CTkSegmentedButton(
            self, values=[SPEAKERS, MIC], command=self._on_source, font=f["small"], height=32,
            corner_radius=8, fg_color=FIELD, selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER, unselected_color=FIELD,
            unselected_hover_color=FIELD_HOVER, text_color=TEXT)
        self.source.grid(row=0, column=1, padx=(0, 8))
        self.menu = ctk.CTkOptionMenu(
            self, width=320, values=[""], font=f["body"], dropdown_font=f["body"],
            height=32, corner_radius=8, fg_color=FIELD, button_color=FIELD,
            button_hover_color=FIELD_HOVER, dropdown_fg_color=CARD,
            dropdown_hover_color=FIELD_HOVER, text_color=TEXT, dropdown_text_color=TEXT,
            dynamic_resizing=False, command=self._on_device)
        self.menu.grid(row=0, column=2, padx=(0, 8))
        ctk.CTkButton(self, text="⟳", font=ctk.CTkFont(FONT, 16), width=32, height=32,
                      corner_radius=8, fg_color=FIELD, hover_color=FIELD_HOVER, text_color=TEXT,
                      command=self.refresh).grid(row=0, column=3)
        self.refresh()

    def refresh(self):
        """Lists the devices again (and shows the current settings)."""
        source = self.settings.get("audio_source", SPEAKERS)
        if source not in _PREFIX:
            source = SPEAKERS
        self.source.set(source)
        try:
            found = audio.list_devices()
        except OSError:
            found = []
        prefix = _PREFIX[source]
        self.devices = [(label[len(prefix):], i) for label, i in found if label.startswith(prefix)]
        names = [d[0] for d in self.devices] or [
            "No speakers found" if source == SPEAKERS else "No microphone found"]
        self.menu.configure(values=names)
        saved = self.settings.get("audio_device", "")
        match = [n for n, _ in self.devices if prefix + n == saved]
        self.menu.set(match[0] if match else names[0])
        if self.devices:
            self.settings["audio_device"] = prefix + self.menu.get()

    def device_index(self):
        """The chosen device's index, or None if there's none."""
        return dict(self.devices).get(self.menu.get())

    def _on_source(self, source):
        self.settings["audio_source"] = source
        self.settings["audio_device"] = ""  # the default device of that source
        self.refresh()
        if self.on_change:
            self.on_change()

    def _on_device(self, name):
        self.settings["audio_device"] = _PREFIX[self.source.get()] + name
        if self.on_change:
            self.on_change()
