"""Turns keystrokes into predictions and predictions into key lights.

The hook thread feeds key presses in; a sender thread pushes frames to every
enabled keyboard (immediately when the lit keys change, and periodically as a
keep-alive, since some keyboards fall back to their own lighting otherwise).
"""

import queue
import threading
import time

import devices
import keys
from devices import DeviceError
from predict import ENGLISH, WORD_CHARS
from secure import PasswordDetector

VK_BACK, VK_TAB, VK_RETURN, VK_ESCAPE = 0x08, 0x09, 0x0D, 0x1B
# Keys that move the caret or change text in ways we can't follow.
VK_RESET = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E}
MAX_TEXT = 200
AUTO = "auto"
_TOGGLE_PRIVATE = object()
RETRY_S = 5.0


class DeviceSlot:
    """A keyboard plus what the UI shows about it."""

    def __init__(self, kb, enabled):
        self.kb = kb
        self.enabled = enabled
        self.opened = False
        self.status = "ready"
        self.ok = True
        self.last_sent = 0.0
        self.sent_frame = None
        self.failed_at = 0.0


class Engine:
    def __init__(self, models, detector, settings):
        self.models = models
        self.detector = detector
        self.settings = settings
        self.text = ""
        self.window = None
        self.mode = ENGLISH if self.auto else settings.get("mode", ENGLISH)
        self.mode_reason = ""
        self.secret = False      # typing in a password field: nothing recorded, keys dark
        self.private = False     # same, switched on by hand (hotkey) for prompts we can't detect
        self.secure = None       # PasswordDetector, created on the sender thread
        self.on_private = None   # callback(bool) when private mode changes (e.g. a sound)
        self.predictions = []
        self.lit = {}            # key id -> rank (0 best)
        self.paused = False
        self.idle = False
        self.last_key = time.monotonic()
        self.version = 0         # bumped whenever something the UI shows changes
        self.slots = []
        self.problems = []
        self.lock = threading.RLock()
        self._events = queue.SimpleQueue()
        self._wake = threading.Event()
        self._stop = False
        self._predict()

    # ------------------------------------------------------------- devices

    def scan(self):
        found, problems = devices.scan_all()
        disabled = set(self.settings.get("disabled_devices", []))
        with self.lock:
            for slot in self.slots:
                self._close(slot)
            self.slots = [DeviceSlot(kb, kb.id not in disabled) for kb in found]
            for slot in self.slots:
                if not slot.kb.available:
                    slot.status, slot.ok = slot.kb.hint, True
            self.problems = problems
            self.version += 1
        self._wake.set()

    def set_enabled(self, slot, enabled):
        with self.lock:
            slot.enabled = enabled
            if not enabled:
                self._close(slot)
                slot.status, slot.ok = "off", True
            disabled = {s.kb.id for s in self.slots if not s.enabled}
            self.settings["disabled_devices"] = sorted(disabled)
            self.version += 1
        self._wake.set()

    def set_paused(self, paused):
        with self.lock:
            self.paused = paused
            if paused:
                for slot in self.slots:
                    self._release(slot)
            self.version += 1
        self._wake.set()

    # ---------------------------------------------------------------- modes

    @property
    def auto(self):
        return self.settings.get("mode", AUTO) == AUTO

    def set_mode(self, mode):
        """mode: a mode id, or AUTO to follow the window being typed in."""
        with self.lock:
            self.settings["mode"] = mode
            if mode != AUTO:
                self._switch(mode, "chosen")
            elif self.window:
                self._switch(*self.detector.detect(self.window))
            self._predict()
            self.version += 1
        self._wake.set()

    def _switch(self, mode, reason):
        if mode != self.mode:
            self.mode = mode
            self.text = ""
        self.mode_reason = reason

    # ----------------------------------------------------------- keystrokes

    def on_key(self, ev):
        """Called on the hook thread: just queue it."""
        self._events.put(ev)
        self._wake.set()

    def toggle_private(self):
        """Hotkey / button. Safe to call from the hook thread (only queues)."""
        self._events.put(_TOGGLE_PRIVATE)
        self._wake.set()

    def _set_private(self, on):
        self.private = on
        self.text = ""  # nothing typed before or during private mode is kept
        if self.on_private:
            self.on_private(on)

    def _handle(self, ev):
        if ev is _TOGGLE_PRIVATE:
            self._set_private(not self.private)
            return True
        if self.private:
            return False
        if ev.window != self.window:  # switched windows: fresh context
            self.window = ev.window
            self.text = ""
        if self.secure is not None and self.secure.focused_is_password():
            self.text = ""  # forget the context around a password, too
            changed, self.secret = not self.secret, True
            return changed
        if self.secret:  # just left the password field
            self.secret = False
            self.text = ""
        if self.auto:
            self._switch(*self.detector.detect(ev.window))
        model = self.models.get(self.mode)
        text = self.text
        if ev.ctrl or ev.alt or ev.win:
            if ev.ctrl and not ev.alt and ev.vk == VK_BACK:  # delete word
                text = text.rstrip()
                while text and text[-1] in WORD_CHARS:
                    text = text[:-1]
            else:  # shortcuts (paste, undo, ...) and AltGr characters: unknown text
                text = ""
        elif ev.vk == VK_BACK:
            text = text[:-1]
        elif ev.vk == VK_RETURN and self.mode != ENGLISH:  # code / terminal: next line
            text = (text + "\n")[-MAX_TEXT:]
            model.observe(text)
        elif ev.vk in (VK_RETURN, VK_TAB, VK_ESCAPE) or ev.vk in VK_RESET:
            text = ""
        else:
            ch = self._char(ev)
            if ch is None:
                return False
            text = (text + ch)[-MAX_TEXT:]
            model.observe(text)
        self.text = text
        return True

    @staticmethod
    def _char(ev):
        key = keys.VK.get(ev.vk)
        if key is not None:
            if key == "space":
                return " "
            if ev.shift and key in keys.SHIFTED:
                return keys.SHIFTED[key]
            return key
        return keys.VK_NUMPAD.get(ev.vk)

    def _predict(self):
        """Lights the keys of the 3 best guesses (characters on the same key,
        like ' and \", count once)."""
        lit, chosen = {}, []
        if self.secret or self.private:
            self.lit, self.predictions = lit, chosen
            return
        for ch in self.models.get(self.mode).predict(self.text):
            key = keys.char_key(ch)
            if key and key not in lit:
                lit[key] = len(lit)
                chosen.append(ch)
                if len(lit) == 3:
                    break
        self.lit, self.predictions = lit, chosen

    # -------------------------------------------------------------- frames

    def frame_for(self, kb):
        colors = self.settings["colors"]
        if kb.white_only:
            colors = [(v, v, v) for v in self.settings["white_levels"]]
        frame = [(0, 0, 0)] * kb.n
        for key, rank in self.lit.items():
            for i in kb.keymap.get(key, ()):
                if i < kb.n:
                    frame[i] = tuple(colors[rank])
        return frame

    def run(self):
        """Sender thread: processes keystrokes and keeps every keyboard lit."""
        self.secure = PasswordDetector()
        while not self._stop:
            idle_s = self.settings.get("idle_release_s", 0)
            self._wake.wait(0.25)
            self._wake.clear()
            changed = False
            while True:
                try:
                    ev = self._events.get_nowait()
                except queue.Empty:
                    break
                with self.lock:
                    if self._handle(ev):
                        changed = True
                    self.last_key = time.monotonic()
                    if self.idle:
                        self.idle, changed = False, True
            with self.lock:
                if changed:
                    self._predict()
                    self.version += 1
                if idle_s and not self.idle and time.monotonic() - self.last_key > idle_s:
                    self.idle = True
                    for slot in self.slots:
                        self._release(slot)
                    self.version += 1
                slots = list(self.slots) if not (self.paused or self.idle) else []
            for slot in slots:
                self._service(slot)

    def _service(self, slot):
        with self.lock:
            if not slot.enabled or not slot.kb.available:
                return
            now = time.monotonic()
            if not slot.ok and now - slot.failed_at < RETRY_S:
                return
            frame = self.frame_for(slot.kb)
            due = frame != slot.sent_frame or now - slot.last_sent >= slot.kb.keepalive
            if not due:
                return
            try:
                if not slot.opened:
                    slot.kb.open()
                    slot.opened = True
                slot.kb.send(frame)
                slot.sent_frame, slot.last_sent = frame, now
                if not slot.ok or slot.status != "lit":
                    slot.status, slot.ok = "lit", True
                    self.version += 1
            except DeviceError as e:
                self._close(slot)
                slot.status, slot.ok, slot.failed_at = str(e), False, now
                self.version += 1

    def _release(self, slot):
        try:
            slot.kb.release()
        except DeviceError:
            pass
        slot.sent_frame = None
        if slot.ok and slot.enabled:
            slot.status = "paused" if self.paused else "idle"

    def _close(self, slot):
        if slot.opened or slot.sent_frame is not None:
            slot.kb.close()
        slot.opened = False
        slot.sent_frame = None

    def stop(self):
        self._stop = True
        self._wake.set()
        with self.lock:
            for slot in self.slots:
                self._close(slot)
