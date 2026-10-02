"""Any per-key keyboard OpenRGB supports (Corsair, SteelSeries, HyperX, ASUS,
Keychron with OpenRGB-protocol QMK, Logitech/Razer without their vendor apps, ...).

Needs OpenRGB running with its SDK server started (port 6742). Keys are found
by OpenRGB's LED names ("Key: A", "Key: Space", ...).
"""

import threading

from .base import DeviceError, Keyboard

HOST, PORT = "127.0.0.1", 6742
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


class _Client:
    lock = threading.Lock()
    client = None

    @classmethod
    def get(cls):
        if cls.client is None:
            from openrgb import OpenRGBClient
            try:
                cls.client = OpenRGBClient(HOST, PORT, name="Predictive Key Lights")
            except (OSError, TimeoutError) as e:
                raise DeviceError(f"Can't reach OpenRGB on port {PORT} - is its SDK "
                                  f"server started? ({e})") from e
        return cls.client

    @classmethod
    def drop(cls):
        try:
            cls.client.disconnect()
        except (OSError, AttributeError):
            pass
        cls.client = None


class OpenRGBKeyboard(Keyboard):
    keepalive = 2.0

    def __init__(self, index, dev, keymap):
        self.index = index
        self.dev_name = dev.name
        self.dev = dev
        self.id = f"openrgb:{dev.name}:{index}"
        self.name = dev.name
        self.detail = f"OpenRGB · {len(keymap)} typing keys found"
        self.n = len(dev.leds)
        self.keymap = keymap
        self.saved_mode = None

    def send(self, rgb):
        from openrgb.utils import RGBColor
        with _Client.lock:
            try:
                if self.saved_mode is None:  # take over: switch to direct control
                    devices = _Client.get().devices
                    self.dev = next((d for d in devices if d.name == self.dev_name), None)
                    if self.dev is None:
                        raise DeviceError(f"OpenRGB no longer lists {self.dev_name}")
                    self.saved_mode = self.dev.active_mode
                    self.dev.set_custom_mode()
                self.dev.set_colors([RGBColor(*c) for c in rgb], fast=True)
            except (OSError, ConnectionError, TimeoutError, ValueError) as e:
                _Client.drop()
                self.saved_mode = None
                raise DeviceError(f"Lost the connection to OpenRGB ({e})") from e

    def release(self):
        with _Client.lock:
            if self.saved_mode is not None:
                try:
                    self.dev.set_mode(self.saved_mode)
                except (OSError, ConnectionError, TimeoutError, ValueError):
                    pass
                self.saved_mode = None


def scan():
    try:
        import openrgb  # noqa: F401
    except ImportError:
        return []
    with _Client.lock:
        _Client.drop()
        try:
            client = _Client.get()
        except DeviceError:
            return []
        found = []
        for i, dev in enumerate(client.devices):
            keymap = {}
            for led in dev.leds:
                key = _key_id(led.name)
                if key:
                    keymap.setdefault(key, []).append(led.id)
            if len(keymap) >= 26:  # has the letter keys at least
                found.append(OpenRGBKeyboard(i, dev, keymap))
        return found
