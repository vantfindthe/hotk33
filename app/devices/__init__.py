"""Device backends. Each module's scan() returns the Outputs it can drive."""

from . import logitech, model100, openrgb_devices, qmk_via, razer
from .base import Output, OutputError

BACKENDS = [
    ("Model 100", model100.scan),
    ("Logitech G HUB", logitech.scan),
    ("Razer Chroma", razer.scan),
    ("OpenRGB", openrgb_devices.scan),
    ("QMK / VIA", qmk_via.scan),
]


def scan_all():
    """Returns (outputs, problems). A failing backend doesn't stop the others."""
    outputs, problems = [], []
    for name, scan in BACKENDS:
        try:
            outputs += scan()
        except Exception as e:  # noqa: BLE001 - one broken backend mustn't hide the rest
            problems.append(f"{name}: {e}")
    return outputs, problems
