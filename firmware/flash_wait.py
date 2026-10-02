"""Reboots the Model 100 into its bootloader (Prog must be held) and flashes
build/Model100.ino.bin with dfu-util. Usage: flash_wait.py [COMport]"""

import glob
import os
import subprocess
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "build", "Model100.ino.bin")
DFU = glob.glob(os.path.expandvars(
    r"%LOCALAPPDATA%\Arduino15\packages\keyboardio\tools\dfu-util\*\dfu-util.exe"))[0]


def dfu_present():
    out = subprocess.run([DFU, "-l"], capture_output=True, text=True).stdout
    return "Found DFU" in out and "3496" in out


print("Hold the Prog key (top-left) on the Model 100 ...", flush=True)
deadline = time.time() + 120
last_reset = 0
while time.time() < deadline:
    if dfu_present():
        print("Bootloader found, flashing ...", flush=True)
        r = subprocess.run([DFU, "-d", "3496:0005", "-D", BIN, "-R"])
        print("dfu-util exit code", r.returncode, flush=True)
        sys.exit(r.returncode)
    if time.time() - last_reset > 6:
        try:
            with serial.Serial(PORT, 115200, timeout=1) as s:
                s.write(b"device.reset\n")
                s.flush()
                time.sleep(0.3)
            print("Sent device.reset", flush=True)
        except (OSError, serial.SerialException):
            pass
        last_reset = time.time()
    time.sleep(0.5)
print("Timed out waiting for the bootloader.")
sys.exit(1)
