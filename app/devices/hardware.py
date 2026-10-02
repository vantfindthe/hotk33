"""Which keyboards are physically connected, by brand (USB vendor id).

Used to name devices, and to tell the user what's missing when a keyboard is
plugged in but no backend can drive it yet (vendor app not running, Bluetooth
connection, ...).
"""

from .base import Keyboard

BRANDS = {
    0x046D: "Logitech", 0x1532: "Razer", 0x3434: "Keychron", 0x1038: "SteelSeries",
    0x1B1C: "Corsair", 0x0951: "HyperX", 0x03F0: "HyperX", 0x0B05: "ASUS",
    0x3496: "Keyboardio",
}
BUS_BLUETOOTH = 2  # hidapi bus_type

# What to do when a brand's keyboard is connected but nothing drives it.
SETUP_HINTS = {
    "Logitech": "Start Logitech G HUB (or OpenRGB with G HUB closed)",
    "Razer": "Start Razer Synapse with Chroma Connect (or OpenRGB with Synapse closed)",
    "Keychron": "Start OpenRGB 1.0+ with its SDK Server (needs Keychron firmware 1.1.1+)",
    "SteelSeries": "Start SteelSeries GG / Engine",
    "Corsair": "Start OpenRGB with its SDK Server (close iCUE)",
    "HyperX": "Start OpenRGB with its SDK Server (close NGENUITY)",
    "ASUS": "Start OpenRGB with its SDK Server (close Armoury Crate)",
    "Keyboardio": "Flash the MusicLEDs firmware (github.com/vantfindthe/rgb-music-visualizer) "
                  "and close Chrysalis",
}
BLUETOOTH_HINT = "Connected wirelessly - per-key lighting from a PC needs the USB cable"


def detect():
    """[{"brand", "product", "bluetooth"}] for each connected keyboard (by product)."""
    try:
        import hid
        infos = hid.enumerate()
    except (ImportError, OSError):
        return []
    found = {}
    for d in infos:
        brand = BRANDS.get(d.get("vendor_id"))
        if not brand or d.get("usage_page") != 1 or d.get("usage") != 6:
            continue
        product = (d.get("product_string") or "").strip()
        if not product or product == "HID VHF Driver" or "mouse" in product.lower():
            continue
        key = (d["vendor_id"], d["product_id"])
        entry = found.setdefault(key, {"brand": brand, "product": product, "bluetooth": False})
        if d.get("bus_type") == BUS_BLUETOOTH:
            entry["bluetooth"] = True
    return list(found.values())


def product_name(brand):
    """The product name of a connected keyboard of `brand`, if exactly one."""
    names = [d["product"] for d in detect() if d["brand"] == brand]
    return names[0] if len(names) == 1 else ""


class SetupHint(Keyboard):
    """A connected keyboard that can't be lit yet; shown with what to do."""

    available = False

    def __init__(self, brand, product, hint):
        self.id = f"hint:{brand}:{product}"
        self.name = product if product.lower().startswith(brand.lower()) else f"{brand} {product}"
        self.detail = "detected - not lit yet"
        self.hint = hint

    def send(self, rgb):
        pass


def hints(outputs):
    """SetupHints for connected keyboards whose brand no output covers."""
    covered = " ".join(f"{o.name} {o.id}" for o in outputs).lower()
    out = []
    for d in detect():
        if d["brand"].lower() in covered:
            continue
        hint = BLUETOOTH_HINT if d["bluetooth"] else SETUP_HINTS.get(d["brand"], "")
        out.append(SetupHint(d["brand"], d["product"], hint))
    return out
