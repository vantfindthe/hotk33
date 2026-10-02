"""Common interface for the keyboards the illuminator can light up."""


class DeviceError(Exception):
    """A keyboard couldn't be opened or written. The message is shown to the user."""


class Keyboard:
    """One per-key lightable keyboard. Subclasses set these and implement send().

    id         stable id
    name       shown in the device list
    detail     second line in the device list (backend, how it's connected)
    n          number of LEDs in a frame
    keymap     key id (see keys.py) -> LED indices in the frame
    white_only per-key brightness but no color: ranks are shown as brightness
    keepalive  resend the frame at least this often (s); devices fall back to
               their own lighting when frames stop
    available  False for keyboards that are only detected (see hardware.SetupHint)
    """

    id = ""
    name = ""
    detail = ""
    n = 0
    keymap = {}
    white_only = False
    keepalive = 1.0
    available = True
    hint = ""

    def open(self):
        """Prepares the device. Raises DeviceError."""

    def send(self, rgb):
        """Shows one frame. rgb: list of n (r, g, b) tuples. Raises DeviceError."""
        raise NotImplementedError

    def release(self):
        """Hands the lighting back to the keyboard's own effects / vendor app."""

    def close(self):
        """Releases the device. Must not raise."""
        try:
            self.release()
        except DeviceError:
            pass
