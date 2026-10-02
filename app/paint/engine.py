"""Paint mode's render loop: draws every enabled device's painted pattern
(animated) and streams it, one sender thread per device. Key presses, from
the keyboard hook, heat up the keys painted with a heatmap reaction and make
the keystroke-reactive ones ripple; audio (captured only while something
reacts to it) drives the audio-reactive ones."""

import math
import queue
import threading
import time

import numpy as np

import keys
from music import audio
from music.engine import OutputWorker, device_frame
from .pattern import AUDIO, HEAT_PER_PRESS, MAX_HEAT, PULSE_S, render, ripple

FPS = 40
VK_RETURN = 0x0D


def key_of(vk):
    """Key id (keys.py) of a virtual-key code, for the typing keys."""
    return "enter" if vk == VK_RETURN else keys.VK.get(vk)


class PaintEngine(threading.Thread):
    """pattern_of(output) -> its Pattern or None. `outputs` (the enabled
    devices) and `preview` (shown on screen) can be changed any time; devices
    start streaming once they have something painted, and get their own
    lighting back when their pattern is cleared or they're switched off.

    What gets drawn comes from scene() / lit() / draw() / reaction_of();
    Styles mode overrides them to draw its effects through the same loop."""

    def __init__(self, outputs, pattern_of, settings, audio_device=lambda: None):
        """audio_device() -> index of the audio device to follow, or None."""
        super().__init__(daemon=True)
        self.audio_device = audio_device
        self.analyzer = audio.Analyzer()
        self.audio_error = ""
        self._capture = None
        self._capture_index = None
        self.presses = []   # (time, key id or None), for the keystroke ripple
        self.outputs = list(outputs)
        self.pattern_of = pattern_of
        self.settings = settings
        self.preview = None
        self.workers = {}   # output id -> OutputWorker
        self.frames = {}    # output id -> float RGB frame, for the preview
        self.heat = {}      # output id -> per-LED heat
        self.fps = 0
        self._events = queue.SimpleQueue()
        self._quit = threading.Event()

    def stop(self):
        self._quit.set()

    def on_key(self, ev):
        """Called on the hook thread: just queue it."""
        self._events.put(ev.vk)

    # ---- what to draw (overridden by Styles mode)

    def scene(self, devices):
        """{output id: what to draw on it} for the devices that have something."""
        out = {}
        for d in devices:
            pattern = self.pattern_of(d)
            if pattern is not None and pattern.n == d.layout.n:
                out[d.id] = pattern
        return out

    def lit(self, source):
        """Whether `source` lights anything (otherwise the device isn't taken over)."""
        return not source.empty

    def wants_audio(self, scene):
        return any(p.uses(AUDIO) for p in scene.values())

    def reaction_of(self, out):
        """Per-LED heat added by a press of the LED's key, or None."""
        pattern = self.pattern_of(out)
        return pattern.reaction if pattern is not None else None

    def heat_fade(self):
        return self.settings["paint_heat_fade"]

    def draw(self, out, source, t, now, heat, presses, bands):
        """(n, 3) float RGB 0..1 for `out`. presses: [(time, center LED or None)]."""
        return render(source, out.layout, t, max(0.2, self.settings["paint_period"]), heat,
                      ripple(out.layout, presses, now), bands)

    # ---- the loop

    def _press(self, key, devices, secure, now):
        if secure is not None and secure.focused_is_password():
            # the lights mustn't show where a password was typed: a flash
            # everywhere, no ripple from the key, no heat
            self.presses.append((now, None))
            return
        self.presses.append((now, key))
        for out in devices:
            reaction = self.reaction_of(out)
            leds = out.keymap.get(key) if reaction is not None else None
            if not leds:
                continue
            n = len(reaction)
            heat = self.heat.setdefault(out.id, np.zeros(n))
            if len(heat) != n:
                heat = self.heat[out.id] = np.zeros(n)
            leds = [i for i in leds if i < n]
            heat[leds] = np.minimum(heat[leds] + reaction[leds] * HEAT_PER_PRESS, MAX_HEAT)

    def _sync_workers(self, wanted):
        for out_id in [i for i in self.workers if i not in wanted]:
            self.workers.pop(out_id).stop()  # it hands the lighting back as it closes
        for out_id, out in wanted.items():
            if out_id not in self.workers:
                w = self.workers[out_id] = OutputWorker(out)
                w.start()

    def _audio(self, wanted):
        """Starts / stops / switches audio capture; returns the band levels or None."""
        index = self.audio_device() if wanted else None
        if index != self._capture_index:
            if self._capture is not None:
                self._capture.stop()
                self._capture = None
            self._capture_index = index
            if index is not None:
                try:
                    self._capture = audio.AudioCapture()
                    self._capture.start(index)
                    self.audio_error = ""
                except OSError as e:
                    self._capture = None
                    self.audio_error = f"Couldn't open the audio device: {e}"
            elif wanted:
                self.audio_error = "Pick an audio device for the audio reaction."
        if wanted and index is None:
            self.audio_error = "Pick an audio device for the audio reaction."
        elif not wanted:
            self.audio_error = ""
        if self._capture is None:
            return None
        self.analyzer.process(self._capture.snapshot(), self._capture.rate)
        return self.analyzer.bands

    def run(self):
        try:
            from predictive.secure import PasswordDetector
            secure = PasswordDetector()
        except Exception:  # noqa: BLE001 - no password check without UI Automation / Win32
            secure = None
        start = last = time.monotonic()
        frame_times = []
        while not self._quit.is_set():
            now = time.monotonic()
            dt, last = now - last, now
            outputs, preview = self.outputs, self.preview
            devices = outputs + ([preview] if preview is not None and preview not in outputs
                                 else [])
            while True:
                try:
                    key = key_of(self._events.get_nowait())
                except queue.Empty:
                    break
                if key:
                    self._press(key, devices, secure, now)
            self.presses = [p for p in self.presses if now - p[0] < PULSE_S * 6 + 1][-24:]
            fade = max(0.1, self.heat_fade())
            for heat in self.heat.values():
                heat *= math.exp(-dt / fade)

            scene = self.scene(devices)
            self._sync_workers({o.id: o for o in outputs
                                if o.id in scene and self.lit(scene[o.id])})
            bands = self._audio(self.wants_audio(scene))

            t = now - start
            frames = {}
            for out in devices:
                source = scene.get(out.id)
                if source is None:
                    continue
                presses = [(pt, out.keymap[k][0] if k in out.keymap else None)
                           for pt, k in self.presses]
                colors = np.clip(self.draw(out, source, t, now, self.heat.get(out.id), presses,
                                           bands), 0, 1)
                frames[out.id] = colors
                if out.id in self.workers:
                    self.workers[out.id].submit(device_frame(colors, out))
            self.frames = frames

            frame_times = [x for x in frame_times if now - x < 1] + [now]
            self.fps = len(frame_times)
            delay = 1 / FPS - (time.monotonic() - now)
            if delay > 0:
                self._quit.wait(delay)

        if self._capture is not None:
            self._capture.stop()
        workers = list(self.workers.values())
        self.workers = {}
        for w in workers:
            w.stop()
        for w in workers:
            w.join(timeout=2)
