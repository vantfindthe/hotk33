"""SteelSeries keyboards (Apex and others), through GameSense in SteelSeries GG.

GameSense is a local JSON API. We register as a "game" and bind one event whose
handlers give every typing key its own color, read from the event's frame
("context-color" handlers on single-key "custom-zone-keys" zones, by HID
usage code). Each frame is one event.
"""

import http.client
import json
import os
import threading
from pathlib import Path

from . import hardware
from .base import DeviceError, Keyboard

CORE_PROPS = (Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
              / "SteelSeries" / "SteelSeries Engine 3" / "coreProps.json")
GAME = "PREDICTIVE_KEY_LIGHTS"
EVENT = "LIGHTS"

# key id -> HID keyboard usage code
HID = {chr(ord("a") + i): 4 + i for i in range(26)}
HID.update({str(d): 30 + (d - 1) % 10 for d in range(10)})
HID.update({"enter": 40, "space": 44, "-": 45, "=": 46, "[": 47, "]": 48, "\\": 49,
            ";": 51, "'": 52, "`": 53, ",": 54, ".": 55, "/": 56})


def _address():
    try:
        return json.loads(CORE_PROPS.read_text(encoding="utf-8"))["address"]
    except (OSError, ValueError, KeyError):
        return None


class SteelSeriesKeyboard(Keyboard):
    keepalive = 1.0  # events also keep the game from timing out

    def __init__(self, address, product):
        self.address = address
        self.id = "steelseries:keyboard"
        self.name = product or "SteelSeries keyboard"
        if not self.name.lower().startswith("steelseries"):
            self.name = f"SteelSeries {self.name}"
        self.detail = "GameSense (SteelSeries GG) · per-key RGB"
        self.order = list(HID)
        self.n = len(self.order)
        self.keymap = {k: [i] for i, k in enumerate(self.order)}
        self.bound = False
        self.value = 0
        self.lock = threading.Lock()

    def _post(self, path, body):
        host, _, port = self.address.partition(":")
        conn = http.client.HTTPConnection(host, int(port), timeout=2)
        try:
            conn.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
            resp = conn.getresponse()
            data = resp.read()
            if resp.status >= 300:
                raise OSError(f"HTTP {resp.status}: {data[:200]!r}")
        finally:
            conn.close()

    def _bind(self):
        self._post("/game_metadata", {"game": GAME, "game_display_name": "Predictive Key Lights",
                                      "developer": "Predictive Key Lights",
                                      "deinitialize_timer_length_ms": 3000})
        keys_handlers = [{"device-type": "rgb-per-key-zones", "custom-zone-keys": [HID[k]],
                          "mode": "context-color", "context-frame-key": f"k{HID[k]}"}
                         for k in self.order]
        dark = {"device-type": "rgb-per-key-zones", "zone": "all", "mode": "color",
                "color": {"red": 0, "green": 0, "blue": 0}}
        event = {"game": GAME, "event": EVENT, "min_value": 0, "max_value": 100,
                 "icon_id": 0, "value_optional": True}
        try:
            self._post("/bind_game_event", {**event, "handlers": [dark] + keys_handlers})
        except OSError:  # some models have no "all" zone: the other keys keep their light
            self._post("/bind_game_event", {**event, "handlers": keys_handlers})
        self.bound = True

    def send(self, rgb):
        with self.lock:
            try:
                if not self.bound:
                    self._bind()
                self.value = self.value % 100 + 1  # a changed value makes GG redraw
                frame = {f"k{HID[k]}": {"red": r, "green": g, "blue": b}
                         for k, (r, g, b) in zip(self.order, rgb)}
                self._post("/game_event", {"game": GAME, "event": EVENT,
                                           "data": {"value": self.value, "frame": frame}})
            except (OSError, http.client.HTTPException, ValueError) as e:
                self.bound = False
                raise DeviceError(f"SteelSeries GG isn't answering - is it running? ({e})") from e

    def release(self):
        with self.lock:
            if self.bound:
                try:
                    self._post("/stop_game", {"game": GAME})  # GG restores its lighting
                except (OSError, http.client.HTTPException, ValueError):
                    pass
                self.bound = False


def scan():
    address = _address()
    if not address:
        return []
    keyboards = [d for d in hardware.detect() if d["brand"] == "SteelSeries"]
    if not keyboards:  # GG is often installed just for a headset or mouse
        return []
    product = keyboards[0]["product"] if len(keyboards) == 1 else ""
    return [SteelSeriesKeyboard(address, product)]
