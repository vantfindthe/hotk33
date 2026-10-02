"""Common interface for everything Hotk33 can light up."""


class OutputError(Exception):
    """A device couldn't be opened or written. The message is shown to the user."""


class Output:
    """One lightable device. Subclasses set these and implement the methods.

    id         stable id, used to remember the device's on/off switch
    name       shown in the device list
    detail     second line in the device list (backend, port, LED count)
    layout     layout.Layout of the device's LEDs, in the order send() expects
    power_budget  optional cap on the summed channel values of a frame

    Per-key keyboards (the ones Typing mode can use) also set:
    keymap     key id (see keys.py) -> indices of its LEDs in the frame
    white_only per-key brightness but no color
    keepalive  Typing mode resends its frame at least this often (s); devices
               fall back to their own lighting when frames stop

    available  False for keyboards that are only detected (hardware.SetupHint);
               `hint` then says what they need
    """

    id = ""
    name = ""
    detail = ""
    layout = None
    power_budget = None
    keymap = {}
    white_only = False
    keepalive = 1.0
    available = True
    hint = ""

    @property
    def music(self):
        """Music mode can drive it."""
        return self.available and self.layout is not None

    @property
    def typing(self):
        """Typing mode can drive it (a keyboard with addressable typing keys)."""
        return self.available and bool(self.keymap)

    def open(self):
        """Prepares the device for streaming. Raises OutputError."""

    def send(self, rgb):
        """Shows one frame. rgb: (layout.n, 3) uint8. Raises OutputError."""
        raise NotImplementedError

    def release(self):
        """Hands the lighting back to the device's own effects / vendor app.
        Streaming resumes with the next send()."""

    def close(self):
        """Releases the device and frees its resources. Must not raise."""
        try:
            self.release()
        except OutputError:
            pass
