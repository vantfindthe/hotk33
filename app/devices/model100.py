"""Keyboardio Model 100, over Kaleidoscope's Focus serial protocol.

Needs the MusicLEDs firmware plugin (firmware/Model100/MusicLEDs.h).
Frames are 64 keys in matrix order: 4 rows x 16 columns, left hand columns
0-7, right hand 8-15. The keymap (for Typing mode) assumes the default QWERTY
layer.
"""

import serial
from serial.tools import list_ports

import layout
from .base import Output, OutputError

KEYBOARDIO_VID = 0x3496
MODEL_100_PID = 0x0006

# key id -> (row, col) in the firmware matrix
_MATRIX = {"`": (1, 0), "space": (1, 8), "enter": (1, 9), "=": (1, 15), "'": (2, 15),
           "-": (3, 15)}
for _row, _cols, _chars in (
        (0, range(1, 6), "12345"), (0, range(10, 15), "67890"),
        (1, range(1, 6), "qwert"), (1, range(10, 15), "yuiop"),
        (2, range(1, 6), "asdfg"), (2, range(10, 15), "hjkl;"),
        (3, range(1, 6), "zxcvb"), (3, range(10, 15), "nm,./")):
    _MATRIX.update({ch: (_row, c) for ch, c in zip(_chars, _cols)})


class Focus:
    def __init__(self, port):
        self.ser = serial.Serial(port, 115200, timeout=0.5, write_timeout=0.5)
        self.ser.reset_input_buffer()

    def command(self, cmd):
        """Sends a Focus command and returns its reply (without the '.' line)."""
        self.ser.write(cmd.encode("ascii") + b"\n")
        reply = self.ser.read_until(b"\r\n.\r\n")
        if not reply.endswith(b"\r\n.\r\n"):
            raise TimeoutError(f"No reply from keyboard to {cmd.split()[0]!r}")
        return reply[:-5].decode("ascii", errors="replace").strip()

    def close(self):
        try:
            self.ser.close()
        except OSError:
            pass


class Model100(Output):
    power_budget = 64 * 255  # every key at one full channel - keeps USB draw sane
    keepalive = 0.5  # the firmware gives the LEDs back after 1.5 s without a frame

    def __init__(self, port):
        self.port = port
        self.id = f"model100:{port}"
        self.name = "Keyboardio Model 100"
        self.detail = f"USB serial · {port}"
        self.layout = layout.model100()
        self.keymap = {k: [r * 16 + c] for k, (r, c) in _MATRIX.items()}
        self.focus = None

    def open(self):
        try:
            self.focus = Focus(self.port)
            if "music.frame" not in self.focus.command("help").split():
                self.focus.close()
                self.focus = None
                raise OutputError("Firmware can't take LED frames - flash the MusicLEDs "
                                  "firmware (see README).")
        except (OSError, serial.SerialException, TimeoutError) as e:
            self.focus = None
            raise OutputError(f"Can't open {self.port} - is Chrysalis (or another lighting "
                              f"app) open? ({e})") from e

    def send(self, rgb):
        try:
            self.focus.command("music.frame " + rgb.tobytes().hex())
        except (OSError, serial.SerialException, TimeoutError) as e:
            raise OutputError(f"Lost the keyboard ({e})") from e

    def release(self):
        if self.focus:
            try:
                self.focus.command("music.stop")
            except (OSError, serial.SerialException, TimeoutError):
                pass

    def close(self):
        if self.focus:
            self.release()
            self.focus.close()
            self.focus = None


def scan():
    return [Model100(p.device) for p in list_ports.comports()
            if p.vid == KEYBOARDIO_VID and p.pid == MODEL_100_PID]
