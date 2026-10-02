"""Keychron and other QMK keyboards with VIA enabled, over VIA's raw-HID protocol.

Stock VIA firmware can't stream per-key colors, so the whole board follows the
music's color and brightness. Changes are made without writing to the
keyboard's EEPROM, and the original lighting is restored afterwards.
(For per-key effects, flash QMK firmware with the OpenRGB protocol and use
the OpenRGB backend instead.)
"""

import colorsys

import layout
from .base import Output, OutputError

try:
    import hid
except ImportError:
    hid = None

RAW_USAGE_PAGE, RAW_USAGE = 0xFF60, 0x61
KEYCHRON_VID = 0x3434
REPORT = 32

GET_PROTOCOL = 0x01
CUSTOM_SET, CUSTOM_GET = 0x07, 0x08  # id_custom_set_value / get_value (v12+)
LIGHTING_SET, LIGHTING_GET = 0x07, 0x08  # id_lighting_set_value / get_value (older)
UNHANDLED = 0xFF
CH_RGBLIGHT, CH_RGB_MATRIX = 2, 3
VAL_BRIGHTNESS, VAL_EFFECT, VAL_COLOR = 1, 2, 4
# Pre-v12 lighting value ids (rgblight; VIA 2 boards mapped RGB matrix onto them)
OLD_BRIGHTNESS, OLD_EFFECT, OLD_COLOR = 0x80, 0x81, 0x83
EFFECT_SOLID = 1


class ViaKeyboard(Output):
    def __init__(self, info):
        self.path = info["path"]
        maker = (info.get("manufacturer_string") or "").strip()
        product = (info.get("product_string") or "QMK keyboard").strip()
        self.name = product if product.startswith(maker) else f"{maker} {product}".strip()
        serial = info.get("serial_number") or self.path.decode(errors="replace")
        self.id = f"via:{info['vendor_id']:04x}:{info['product_id']:04x}:{serial}"
        brand = "Keychron" if info["vendor_id"] == KEYCHRON_VID else "QMK"
        self.detail = f"{brand} · VIA · whole-board color"
        self.layout = layout.strip(1)
        self.channel = None
        self.dev = None
        self.saved = None
        self._last = None

    # protocol -------------------------------------------------------------

    def _xfer(self, *data):
        try:
            self.dev.write(bytes([0]) + bytes(data).ljust(REPORT, b"\0"))
            reply = self.dev.read(REPORT, 250)
        except (OSError, ValueError) as e:
            raise OutputError(f"Lost the keyboard ({e})") from e
        if not reply:
            raise OutputError("The keyboard didn't answer VIA commands")
        return reply

    def _get(self, value, size):
        if self.channel is None:
            reply = self._xfer(LIGHTING_GET, value)
            return None if reply[0] == UNHANDLED else list(reply[2:2 + size])
        reply = self._xfer(CUSTOM_GET, self.channel, value)
        return None if reply[0] == UNHANDLED else list(reply[3:3 + size])

    def _set(self, value, *data):
        if self.channel is None:
            self._xfer(LIGHTING_SET, value, *data)
        else:
            self._xfer(CUSTOM_SET, self.channel, value, *data)

    # Output ---------------------------------------------------------------

    def open(self):
        if hid is None:
            raise OutputError("The hidapi package isn't installed")
        try:
            self.dev = hid.device()
            self.dev.open_path(self.path)
        except (OSError, ValueError) as e:
            self.dev = None
            raise OutputError(f"Can't open the keyboard - is VIA open in a browser? ({e})") from e

        reply = self._xfer(GET_PROTOCOL)
        version = reply[1] << 8 | reply[2]
        if version >= 12:
            self.ids = (VAL_BRIGHTNESS, VAL_EFFECT, VAL_COLOR)
            for channel in (CH_RGB_MATRIX, CH_RGBLIGHT):
                self.channel = channel
                if self._get(VAL_BRIGHTNESS, 1) is not None:
                    break
            else:
                self.close()
                raise OutputError("This keyboard doesn't expose RGB lighting over VIA")
        else:
            self.channel = None
            self.ids = (OLD_BRIGHTNESS, OLD_EFFECT, OLD_COLOR)
            if self._get(OLD_BRIGHTNESS, 1) is None:
                self.close()
                raise OutputError("This keyboard doesn't expose RGB lighting over VIA")

    def send(self, rgb):
        bright_id, effect_id, color_id = self.ids
        if self.saved is None:  # remember the user's lighting, then go solid
            self.saved = [(i, self._get(i, n)) for i, n in
                          ((effect_id, 1), (color_id, 2), (bright_id, 1))]
            self._set(effect_id, EFFECT_SOLID)
            self._last = None
        h, s, v = colorsys.rgb_to_hsv(*(rgb[0] / 255.0))
        hsv = (round(h * 255), round(s * 255), round(v * 255))
        if hsv != self._last:
            self._set(color_id, hsv[0], hsv[1])
            self._set(bright_id, hsv[2])
            self._last = hsv

    def release(self):
        if self.saved is not None and self.dev is not None:
            for value, data in self.saved:
                if data is not None:
                    self._set(value, *data)
            self.saved = None

    def close(self):
        if self.dev is not None:
            try:
                self.release()
            except OutputError:
                pass
            self.dev.close()
            self.dev = None


def scan():
    if hid is None:
        return []
    found = {}
    for info in hid.enumerate():
        if info.get("usage_page") == RAW_USAGE_PAGE and info.get("usage") == RAW_USAGE:
            out = ViaKeyboard(info)
            found.setdefault(out.id, out)
    return list(found.values())
