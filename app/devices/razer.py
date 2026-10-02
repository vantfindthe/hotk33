"""Razer Chroma devices, through the Chroma SDK's local REST API.

Needs Razer Synapse with the Chroma SDK / Chroma Connect module (the REST
server listens on localhost:54235). The SDK can't list connected devices, so
every device category is offered; categories with no hardware do nothing.
Chroma Link covers Chroma-enabled third-party gear such as Razer's ARGB
controller.
"""

import http.client
import json
import threading
import time
from urllib.parse import urlparse

import numpy as np

import layout
from .base import Output, OutputError

SDK_HOST, SDK_PORT = "localhost", 54235
HEARTBEAT_S = 1.0

# category: (display name, effect type, shape: (rows, cols) grid or n-LED strip)
CATEGORIES = {
    "keyboard": ("Razer keyboard", "CHROMA_CUSTOM", (6, 22)),
    "mouse": ("Razer mouse", "CHROMA_CUSTOM2", (9, 7)),
    "mousepad": ("Razer mousepad", "CHROMA_CUSTOM", 15),
    "headset": ("Razer headset", "CHROMA_CUSTOM", 5),
    "keypad": ("Razer keypad", "CHROMA_CUSTOM", (4, 5)),
    "chromalink": ("Razer Chroma Link / ARGB", "CHROMA_CUSTOM", 5),
}

APP_INFO = {
    "title": "Model 100 Music Visualizer",
    "description": "Makes your lighting react to music",
    "author": {"name": "Music Visualizer", "contact": "localhost"},
    "device_supported": list(CATEGORIES),
    "category": "application",
}


def _request(conn, method, path, body=None):
    conn.request(method, path, body=json.dumps(body) if body is not None else None,
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = resp.read()
    if resp.status >= 300:
        raise OSError(f"HTTP {resp.status}")
    return json.loads(data) if data else {}


class _Session:
    """One Chroma app session shared by all Razer outputs (reference counted),
    kept alive with a heartbeat thread."""

    lock = threading.Lock()
    users = 0
    conn = None
    path = None
    _beat = None

    @classmethod
    def acquire(cls):
        with cls.lock:
            if cls.users == 0:
                try:
                    init = http.client.HTTPConnection(SDK_HOST, SDK_PORT, timeout=2)
                    info = _request(init, "POST", "/razer/chromasdk", APP_INFO)
                    init.close()
                    uri = urlparse(info["uri"])
                    cls.conn = http.client.HTTPConnection(uri.hostname, uri.port, timeout=2)
                    cls.path = uri.path.rstrip("/")
                except (OSError, KeyError, ValueError) as e:
                    raise OutputError(f"Couldn't start a Razer Chroma session - is Synapse "
                                      f"running? ({e})") from e
                time.sleep(0.5)  # the SDK ignores effects sent right after init
                cls._beat = threading.Event()
                threading.Thread(target=cls._heartbeat, args=(cls._beat,), daemon=True).start()
            cls.users += 1

    @classmethod
    def release(cls):
        with cls.lock:
            cls.users -= 1
            if cls.users == 0:
                cls._beat.set()
                try:
                    _request(cls.conn, "DELETE", cls.path)  # Synapse restores its lighting
                except (OSError, ValueError):
                    pass
                cls.conn.close()
                cls.conn = None

    @classmethod
    def put(cls, category, body):
        with cls.lock:
            try:
                _request(cls.conn, "PUT", f"{cls.path}/{category}", body)
            except (OSError, ValueError, http.client.HTTPException) as e:
                raise OutputError(f"Razer Chroma SDK stopped responding ({e})") from e

    @classmethod
    def _heartbeat(cls, stop):
        while not stop.wait(HEARTBEAT_S):
            with cls.lock:
                if cls.conn is None:
                    return
                try:
                    _request(cls.conn, "PUT", f"{cls.path}/heartbeat")
                except (OSError, ValueError, http.client.HTTPException):
                    pass


class RazerDevice(Output):
    def __init__(self, category):
        name, self.effect, shape = CATEGORIES[category]
        self.category = category
        self.id = f"razer:{category}"
        self.name = name
        if isinstance(shape, tuple):
            self.rows, self.cols = shape
            self.layout = layout.grid(self.cols, self.rows)
            self.detail = f"Chroma SDK · {self.rows}x{self.cols} grid"
        else:
            self.rows = None
            self.layout = layout.strip(shape)
            self.detail = f"Chroma SDK · {shape} LEDs"
        self.held = False

    def send(self, rgb):
        if not self.held:
            _Session.acquire()
            self.held = True
        rgb = rgb.astype(np.uint32)
        bgr = (rgb[:, 0] | (rgb[:, 1] << 8) | (rgb[:, 2] << 16)).tolist()
        param = [bgr[r * self.cols:(r + 1) * self.cols] for r in range(self.rows)] if self.rows else bgr
        _Session.put(self.category, {"effect": self.effect, "param": param})

    def release(self):
        if self.held:
            self.held = False
            _Session.release()


def scan():
    try:
        conn = http.client.HTTPConnection(SDK_HOST, SDK_PORT, timeout=0.5)
        _request(conn, "GET", "/razer/chromasdk")
        conn.close()
    except (OSError, ValueError, http.client.HTTPException):
        return []
    return [RazerDevice(c) for c in CATEGORIES]
