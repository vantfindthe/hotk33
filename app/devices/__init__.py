"""Keyboard backends. Each module's scan() returns the Keyboards it can drive."""

from . import hardware, logitech, model100, openrgb_kb, razer, steelseries
from .base import DeviceError, Keyboard

BACKENDS = [
    ("Model 100", model100.scan),
    ("Logitech G HUB", logitech.scan),
    ("Razer Chroma", razer.scan),
    ("SteelSeries GameSense", steelseries.scan),
    ("OpenRGB", openrgb_kb.scan),
]


def scan_all():
    """Returns (keyboards, problems). A failing backend doesn't stop the others.
    Connected keyboards nothing can drive yet come back as hardware.SetupHint."""
    found, problems = [], []
    for name, scan in BACKENDS:
        try:
            found += scan()
        except Exception as e:  # noqa: BLE001 - one broken backend mustn't hide the rest
            problems.append(f"{name}: {e}")
    try:
        found += hardware.hints(found)
    except Exception as e:  # noqa: BLE001
        problems.append(f"Keyboard detection: {e}")
    return found, problems
