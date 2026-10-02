"""Razer Chroma keyboards, through the Chroma SDK's local REST API.

Needs Razer Synapse with the Chroma SDK / Chroma Connect module (REST server on
localhost:54235). The SDK can't list devices, so a keyboard is offered whenever
the SDK answers.
"""

import http.client
import json
import threading
import time
from urllib.parse import urlparse

from . import hardware
from .base import DeviceError, Keyboard

SDK_HOST, SDK_PORT = "localhost", 54235
ROWS, COLS = 6, 22
APP_INFO = {
    "title": "Predictive Key Lights",
    "description": "Lights the keys you're most likely to type next",
    "author": {"name": "Predictive Key Lights", "contact": "localhost"},
    "device_supported": ["keyboard"],
    "category": "application",
}


def _grid():
    """Key id -> (row, col) in the Chroma 6 x 22 keyboard grid."""
    pos = {"`": (1, 1), "-": (1, 12), "=": (1, 13), "[": (2, 12), "]": (2, 13), "\\": (2, 14),
           ";": (3, 11), "'": (3, 12), ",": (4, 10), ".": (4, 11), "/": (4, 12),
           "space": (5, 7), "enter": (3, 14)}
    for row, start, chars in ((1, 2, "1234567890"), (2, 2, "qwertyuiop"),
                              (3, 2, "asdfghjkl"), (4, 3, "zxcvbnm")):
        pos.update({ch: (row, start + i) for i, ch in enumerate(chars)})
    return {k: [r * COLS + c] for k, (r, c) in pos.items()}


def _request(conn, method, path, body=None):
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = resp.read()
    if resp.status >= 300:
        raise OSError(f"HTTP {resp.status}")
    return json.loads(data) if data else {}


class RazerKeyboard(Keyboard):
    keepalive = 1.0  # doubles as the SDK heartbeat

    def __init__(self, product=""):
        self.id = "razer:keyboard"
        self.name = product or "Razer keyboard"
        if not self.name.lower().startswith("razer"):
            self.name = f"Razer {self.name}"
        self.detail = "Chroma SDK · per-key RGB"
        self.n = ROWS * COLS
        self.keymap = _grid()
        self.conn = None
        self.path = None
        self.lock = threading.Lock()

    def _start(self):
        try:
            init = http.client.HTTPConnection(SDK_HOST, SDK_PORT, timeout=2)
            info = _request(init, "POST", "/razer/chromasdk", APP_INFO)
            init.close()
            uri = urlparse(info["uri"])
            self.conn = http.client.HTTPConnection(uri.hostname, uri.port, timeout=2)
            self.path = uri.path.rstrip("/")
        except (OSError, KeyError, ValueError) as e:
            raise DeviceError(f"Couldn't start a Razer Chroma session - is Synapse "
                              f"running? ({e})") from e
        time.sleep(0.5)  # the SDK ignores effects sent right after init

    def send(self, rgb):
        with self.lock:
            if self.conn is None:
                self._start()
            bgr = [r | (g << 8) | (b << 16) for r, g, b in rgb]
            param = [bgr[r * COLS:(r + 1) * COLS] for r in range(ROWS)]
            try:
                _request(self.conn, "PUT", f"{self.path}/keyboard",
                         {"effect": "CHROMA_CUSTOM", "param": param})
                _request(self.conn, "PUT", f"{self.path}/heartbeat")
            except (OSError, ValueError, http.client.HTTPException) as e:
                self.conn = None
                raise DeviceError(f"Razer Chroma SDK stopped responding ({e})") from e

    def release(self):
        with self.lock:
            if self.conn is not None:
                try:
                    _request(self.conn, "DELETE", self.path)  # Synapse restores its lighting
                except (OSError, ValueError, http.client.HTTPException):
                    pass
                self.conn.close()
                self.conn = None


def scan():
    try:
        conn = http.client.HTTPConnection(SDK_HOST, SDK_PORT, timeout=0.5)
        _request(conn, "GET", "/razer/chromasdk")
        conn.close()
    except (OSError, ValueError, http.client.HTTPException):
        return []
    keyboards = [d for d in hardware.detect() if d["brand"] == "Razer"]
    if not keyboards:  # Synapse is often running just for a Razer mouse or headset
        return []
    return [RazerKeyboard(keyboards[0]["product"] if len(keyboards) == 1 else "")]
