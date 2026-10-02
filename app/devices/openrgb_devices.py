"""Everything OpenRGB supports - motherboard ARGB headers, ARGB fan/strip
controllers (Corsair, NZXT, Lian Li, ...), RAM, GPUs, and many keyboards and
mice (Razer, Logitech, Keychron with OpenRGB-protocol QMK firmware, ...).

Needs OpenRGB running with its SDK server enabled (default port 6742).
Keyboards' typing keys (for Typing mode) are found by OpenRGB's LED names
("Key: A", "Key: Space", ...).
"""

import math
import threading

from openrgb import OpenRGBClient
from openrgb.utils import RGBColor, ZoneType

import layout
from .base import Output, OutputError

HOST, PORT = "127.0.0.1", 6742
STRIP_WRAP = 36  # LEDs per row in the preview
_NAMED = {"space": "space", "spacebar": "space", "enter": "enter", "return": "enter",
          "grave": "`", "minus": "-", "equals": "=",
          "semicolon": ";", "quote": "'", "apostrophe": "'", "comma": ",", "period": ".",
          "slash": "/", "forward slash": "/", "backslash": "\\", "left bracket": "[",
          "right bracket": "]"}


def _key_id(led_name):
    if not led_name.startswith("Key: "):
        return None
    name = led_name[5:].strip()
    if name.startswith("\\"):  # "\ (ANSI)" / "\ (ISO)"
        return "\\"
    if len(name) == 1:
        return name.lower()
    return _NAMED.get(name.lower())


def build_keymap(dev):
    """Key id -> LED indices, if the device has (at least) the letter keys."""
    keymap = {}
    for led in dev.leds:
        key = _key_id(led.name)
        if key:
            keymap.setdefault(key, []).append(led.id)
    return keymap if len(keymap) >= 26 else {}


class _Client:
    """One SDK connection shared by all OpenRGB outputs (the client isn't
    thread-safe, so every call goes through `lock`)."""

    lock = threading.Lock()
    client = None

    @classmethod
    def get(cls):
        if cls.client is None:
            try:
                cls.client = OpenRGBClient(HOST, PORT, name="Hotk33")
            except (OSError, TimeoutError) as e:
                raise OutputError(f"Can't reach OpenRGB on port {PORT} - is it running with "
                                  f"the SDK server enabled? ({e})") from e
        return cls.client

    @classmethod
    def drop(cls):
        try:
            cls.client.disconnect()
        except (OSError, AttributeError):
            pass
        cls.client = None


def build_layout(dev):
    """Lays out the device's zones: key matrices as grids, everything else as
    strips, stacked top to bottom. Each zone spans the full effect width."""
    n = len(dev.leds)
    rects, xs, ys, linear = [None] * n, [0.5] * n, [0.5] * n, [True] * n
    y = 0.0

    def place_strip(indices):
        nonlocal y
        count = len(indices)
        for i, g in enumerate(indices):
            rects[g] = (i % STRIP_WRAP, y + i // STRIP_WRAP, 1, 1)
            xs[g] = i / (count - 1) if count > 1 else 0.5
        y += math.ceil(count / STRIP_WRAP) + 0.8

    for zone in dev.zones:
        zn = len(zone.leds)
        if zn == 0:
            continue
        ids = [led.id for led in zone.leds]
        matrix = zone.matrix_map if zone.type == ZoneType.MATRIX else None
        if matrix:
            h, w = len(matrix), max(len(row) for row in matrix)
            placed = set()
            for r, row in enumerate(matrix):
                for c, idx in enumerate(row):
                    if idx is None or idx >= zn or idx in placed:
                        continue
                    g = ids[idx]
                    rects[g] = (c, y + r, 1, 1)
                    xs[g] = c / (w - 1) if w > 1 else 0.5
                    ys[g] = r / (h - 1) if h > 1 else 0.5
                    linear[g] = False
                    placed.add(idx)
            y += h + 0.8
            leftover = [ids[i] for i in range(zn) if i not in placed]
            if leftover:
                place_strip(leftover)
        else:
            place_strip(ids)

    missing = [g for g in range(n) if rects[g] is None]  # LEDs outside any zone
    if missing:
        place_strip(missing)
    return layout.Layout(rects, xs, ys, linear, round_leds=all(linear))


class OpenRGBDevice(Output):
    def __init__(self, index, dev):
        self.index = index
        self.dev_name = dev.name
        self.dev = dev
        self.id = f"openrgb:{dev.name}:{index}"
        self.name = dev.name
        kind = dev.type.name.replace("_", " ").title() if hasattr(dev.type, "name") else "Device"
        zones = len(dev.zones)
        self.detail = (f"OpenRGB · {kind} · {len(dev.leds)} LEDs"
                       + (f" in {zones} zones" if zones > 1 else ""))
        self.layout = build_layout(dev)
        self.keymap = build_keymap(dev)
        self.keepalive = 2.0
        self.saved_mode = None

    def _find(self, client):
        devices = client.devices
        if self.index < len(devices) and devices[self.index].name == self.dev_name:
            return devices[self.index]
        for d in devices:
            if d.name == self.dev_name:
                return d
        raise OutputError(f"OpenRGB no longer lists {self.dev_name}")

    def send(self, rgb):
        with _Client.lock:
            try:
                if self.saved_mode is None:  # take over: switch to direct control
                    self.dev = self._find(_Client.get())
                    self.saved_mode = self.dev.active_mode
                    self.dev.set_custom_mode()
                self.dev.set_colors([RGBColor(r, g, b) for r, g, b in rgb.tolist()], fast=True)
            except (OSError, ConnectionError, TimeoutError, ValueError) as e:
                _Client.drop()
                self.saved_mode = None
                raise OutputError(f"Lost the connection to OpenRGB ({e})") from e

    def release(self):
        with _Client.lock:
            if self.saved_mode is not None:
                try:
                    self.dev.set_mode(self.saved_mode)  # back to the device's own effect
                except (OSError, ConnectionError, TimeoutError, ValueError):
                    pass
                self.saved_mode = None


def scan():
    with _Client.lock:
        _Client.drop()  # pick up devices added since the last scan
        try:
            client = _Client.get()
        except OutputError:
            return []
        return [OpenRGBDevice(i, d) for i, d in enumerate(client.devices) if d.leds]
