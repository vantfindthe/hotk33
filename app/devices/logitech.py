"""Logitech G keyboards, through the LED SDK that ships with G HUB.

Works while G HUB is running with "allow games & applications to control
lighting" on (the default). When we let go, G HUB's own lighting comes back.
"""

import ctypes
import threading
import winreg

from .base import DeviceError, Keyboard

SDK_CLSID = r"SOFTWARE\Classes\CLSID\{a6519e67-7632-4375-afdf-caa889744403}\ServerBinary"
DEFAULT_DLL = r"C:\Program Files\LGHUB\sdks\sdk_legacy_led_x64.dll"
LOGITECH_VID = 0x046D
APP_NAME = b"Predictive Key Lights"

# The bitmap must be sent with target ALL: G HUB ignores it for white-only
# per-key keyboards (G610) when the target is just "per-key RGB".
TARGET_ALL = 0x7
BITMAP_W, BITMAP_H = 21, 6
WHITE_ONLY = ("G610", "G710")


def _bitmap_index():
    """Key id -> index in the SDK's 21 x 6 key bitmap (row-major)."""
    idx = {"`": 21, "-": 32, "=": 33, "[": 53, "]": 54, "\\": 55, ";": 73, "'": 74,
           ",": 93, ".": 94, "/": 95, "space": 110, "enter": 76}
    idx.update({k: 22 + i for i, k in enumerate("1234567890")})
    idx.update({k: 43 + i for i, k in enumerate("qwertyuiop")})
    idx.update({k: 64 + i for i, k in enumerate("asdfghjkl")})
    idx.update({k: 86 + i for i, k in enumerate("zxcvbnm")})
    return {k: [i] for k, i in idx.items()}


def _dll_path():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SDK_CLSID) as key:
            return winreg.QueryValue(key, None)
    except OSError:
        return DEFAULT_DLL


class _Sdk:
    lock = threading.Lock()
    dll = None
    active = False

    @classmethod
    def load(cls):
        if cls.dll is None:
            try:
                dll = ctypes.CDLL(_dll_path())
            except OSError as e:
                raise DeviceError(f"Logitech G HUB's LED SDK isn't installed ({e})") from e
            for fn in ("LogiLedInitWithName", "LogiLedSetTargetDevice",
                       "LogiLedSetLightingFromBitmap"):
                getattr(dll, fn).restype = ctypes.c_bool
            dll.LogiLedInitWithName.argtypes = [ctypes.c_char_p]
            cls.dll = dll
        return cls.dll


class LogitechKeyboard(Keyboard):
    keepalive = 2.0

    def __init__(self, product):
        self.id = "logitech:keyboard"
        self.name = f"Logitech {product}" if product else "Logitech keyboard"
        self.white_only = any(model in product for model in WHITE_ONLY)
        kind = "per-key white" if self.white_only else "per-key RGB"
        self.detail = f"G HUB SDK · {kind}"
        self.n = BITMAP_W * BITMAP_H
        self.keymap = _bitmap_index()
        self._bitmap = (ctypes.c_ubyte * (self.n * 4))()

    def send(self, rgb):
        dll = _Sdk.load()
        with _Sdk.lock:
            if not _Sdk.active:
                if not dll.LogiLedInitWithName(APP_NAME):
                    raise DeviceError("Couldn't connect to G HUB - is it running?")
                _Sdk.active = True
            buf = bytearray(self.n * 4)
            for i, (r, g, b) in enumerate(rgb):
                buf[i * 4:i * 4 + 4] = bytes((b, g, r, 255))
            ctypes.memmove(self._bitmap, bytes(buf), len(buf))
            if not (dll.LogiLedSetTargetDevice(TARGET_ALL)
                    and dll.LogiLedSetLightingFromBitmap(self._bitmap)):
                raise DeviceError("G HUB rejected the lighting update")

    def release(self):
        with _Sdk.lock:
            if _Sdk.active:
                _Sdk.dll.LogiLedShutdown()
                _Sdk.active = False


def _keyboard_products():
    try:
        import hid
        infos = hid.enumerate(LOGITECH_VID, 0)
    except (ImportError, OSError):
        return []
    # Mice also expose a keyboard interface (for macro buttons), so anything
    # with a mouse interface isn't a keyboard.
    products = {}
    for d in infos:
        name = (d.get("product_string") or "").strip()
        if not name or name == "HID VHF Driver":  # G HUB's virtual devices
            continue
        entry = products.setdefault(d["product_id"], [name, set()])
        if d.get("usage_page") == 1:
            entry[1].add(d.get("usage"))
    return [n for n, usages in products.values() if 6 in usages and 2 not in usages]


def scan():
    try:
        _Sdk.load()
    except DeviceError:
        return []
    products = _keyboard_products()
    if not products:
        return []
    return [LogitechKeyboard(products[0] if len(products) == 1 else "")]
