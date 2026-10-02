"""Device backends. Each module's scan() returns the Outputs it can drive."""

from . import hardware, logitech, model100, openrgb_devices, qmk_via, razer, steelseries
from .base import Output, OutputError

BACKENDS = [
    ("Model 100", model100.scan),
    ("Logitech G HUB", logitech.scan),
    ("Razer Chroma", razer.scan),
    ("SteelSeries GameSense", steelseries.scan),
    ("OpenRGB", openrgb_devices.scan),
    ("QMK / VIA", qmk_via.scan),
]


def scan_all():
    """Returns (outputs, problems). A failing backend doesn't stop the others.
    Connected keyboards nothing can drive yet come back as hardware.SetupHint."""
    outputs, problems = [], []
    for name, scan in BACKENDS:
        try:
            outputs += scan()
        except Exception as e:  # noqa: BLE001 - one broken backend mustn't hide the rest
            problems.append(f"{name}: {e}")
    try:
        outputs += hardware.hints(outputs)
    except Exception as e:  # noqa: BLE001
        problems.append(f"Keyboard detection: {e}")
    return outputs, problems
