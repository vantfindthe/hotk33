"""Logitech G devices, through the LED SDK that ships with G HUB.

Works while G HUB is running (G HUB must allow "games & applications to
control lighting", which is the default). When we let go, G HUB's own
lighting comes back.
"""

import ctypes
import threading
import winreg

import numpy as np

import layout
from .base import Output, OutputError

# CLSID under which G HUB registers its LED SDK implementation.
SDK_CLSID = r"SOFTWARE\Classes\CLSID\{a6519e67-7632-4375-afdf-caa889744403}\ServerBinary"
DEFAULT_DLL = r"C:\Program Files\LGHUB\sdks\sdk_legacy_led_x64.dll"
LOGITECH_VID = 0x046D

# The bitmap must be sent with target ALL: G HUB ignores it for white-only
# per-key keyboards (G610) when the target is just "per-key RGB".
TARGET_ALL = 0x7
DEVICE_TYPE_MOUSE = 0x3
BITMAP_W, BITMAP_H = 21, 6
# Keyboards with white-only per-key backlight.
WHITE_ONLY = ("G610", "G710")


def _dll_path():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SDK_CLSID) as key:
            return winreg.QueryValue(key, None)
    except OSError:
        return DEFAULT_DLL


class _Sdk:
    """One SDK session shared by all Logitech outputs, reference counted:
    it's initialized by the first output that sends and shut down (handing
    lighting back to G HUB) when the last one lets go."""

    lock = threading.Lock()
    dll = None
    users = 0

    @classmethod
    def load(cls):
        if cls.dll is None:
            try:
                dll = ctypes.CDLL(_dll_path())
            except OSError as e:
                raise OutputError(f"Logitech G HUB's LED SDK isn't installed ({e})") from e
            for fn in ("LogiLedInitWithName", "LogiLedSetTargetDevice",
                       "LogiLedSetLightingFromBitmap", "LogiLedSetLightingForTargetZone"):
                getattr(dll, fn).restype = ctypes.c_bool
            dll.LogiLedInitWithName.argtypes = [ctypes.c_char_p]
            cls.dll = dll
        return cls.dll

    @classmethod
    def acquire(cls):
        dll = cls.load()
        with cls.lock:
            if cls.users == 0 and not dll.LogiLedInitWithName(b"Music Visualizer"):
                raise OutputError("Couldn't connect to G HUB - is it running?")
            cls.users += 1

    @classmethod
    def release(cls):
        with cls.lock:
            cls.users -= 1
            if cls.users == 0:
                cls.dll.LogiLedShutdown()


class _LogitechOutput(Output):
    def __init__(self):
        self.held = False

    def send(self, rgb):
        if not self.held:
            _Sdk.acquire()
            self.held = True
        with _Sdk.lock:
            if not self._draw(_Sdk.dll, rgb):
                raise OutputError("G HUB rejected the lighting update")

    def release(self):
        if self.held:
            self.held = False
            _Sdk.release()

    @staticmethod
    def _percent(rgb):
        return [int(c) for c in np.round(np.asarray(rgb, dtype=float) / 2.55)]


class LogitechKeyboard(_LogitechOutput):
    """Per-key keyboards, drawn as the SDK's 21 x 6 key bitmap. White-only
    keyboards get each key's brightness from its color."""

    def __init__(self, product):
        super().__init__()
        self.id = "logitech:keyboard"
        self.name = f"Logitech {product}" if product else "Logitech keyboard"
        self.white_only = any(model in product for model in WHITE_ONLY)
        kind = "per-key white" if self.white_only else "per-key"
        self.detail = f"G HUB SDK · {kind} · needs G HUB running"
        self.layout = layout.grid(BITMAP_W, BITMAP_H)
        self._bitmap = (ctypes.c_ubyte * (BITMAP_W * BITMAP_H * 4))()

    def _draw(self, dll, rgb):
        if self.white_only:
            rgb = np.repeat(rgb.max(axis=1, keepdims=True), 3, axis=1)
        bgra = np.empty((len(rgb), 4), dtype=np.uint8)
        bgra[:, 0], bgra[:, 1], bgra[:, 2], bgra[:, 3] = rgb[:, 2], rgb[:, 1], rgb[:, 0], 255
        ctypes.memmove(self._bitmap, bgra.tobytes(), len(self._bitmap))
        return (dll.LogiLedSetTargetDevice(TARGET_ALL)
                and dll.LogiLedSetLightingFromBitmap(self._bitmap))


class LogitechMouse(_LogitechOutput):
    """Mice, by lighting zone (most G mice have two: logo and DPI/strip)."""

    def __init__(self, product, zones=2):
        super().__init__()
        self.id = "logitech:mouse"
        self.name = f"Logitech {product}" if product else "Logitech mouse"
        self.detail = f"G HUB SDK · {zones} zones · needs G HUB running"
        self.layout = layout.strip(zones)

    def _draw(self, dll, rgb):
        return all(dll.LogiLedSetLightingForTargetZone(DEVICE_TYPE_MOUSE, zone, *self._percent(c))
                   for zone, c in enumerate(rgb))


def _logitech_hid():
    """(keyboard product names, mouse product names) of connected Logitech devices."""
    try:
        import hid
        infos = hid.enumerate(LOGITECH_VID, 0)
    except (ImportError, OSError):
        return [], []
    # Group interfaces by product: mice also expose a keyboard interface (for
    # macro buttons), so anything with a mouse interface counts as a mouse.
    products = {}
    for d in infos:
        name = (d.get("product_string") or "").strip()
        if not name or name == "HID VHF Driver":  # G HUB's virtual devices
            continue
        entry = products.setdefault(d["product_id"], [name, set()])
        if d.get("usage_page") == 1:
            entry[1].add(d.get("usage"))
    keyboards = [n for n, usages in products.values() if 6 in usages and 2 not in usages]
    mice = [n for n, usages in products.values() if 2 in usages]
    return keyboards, mice


def scan():
    try:
        _Sdk.load()
    except OutputError:
        return []
    keyboards, mice = _logitech_hid()
    outputs = []
    if keyboards:
        outputs.append(LogitechKeyboard(keyboards[0] if len(keyboards) == 1 else ""))
    if mice:
        outputs.append(LogitechMouse(mice[0] if len(mice) == 1 else ""))
    return outputs
