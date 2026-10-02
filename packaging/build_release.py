"""Builds the release assets into dist/:

  Hotk33-<version>-windows-x64.zip       standalone app (no Python needed)
  Model100-MusicLEDs-<version>.bin       Keyboardio Model 100 firmware

Run with the app's virtualenv:  .venv\Scripts\python.exe packaging\build_release.py
Needs PyInstaller (packaging/requirements-dev.txt). The firmware is rebuilt
when arduino-cli with the keyboardio:gd32 core is available, otherwise the
existing firmware/build/Model100.ino.bin is used.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
DIST = ROOT / "dist"
WORK = ROOT / "build"
sys.path.insert(0, str(APP))

from version import __version__  # noqa: E402
from widgets import app_icon  # noqa: E402

ARDUINO_CLI = ROOT / "tools" / "arduino-cli" / "arduino-cli.exe"
FQBN = "keyboardio:gd32:keyboardio_model_100"


def build_app():
    WORK.mkdir(exist_ok=True)
    icon = WORK / "icon.ico"
    app_icon().save(icon, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    typing_data = APP / "predictive"
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", "Hotk33", "--icon", str(icon),
        "--paths", str(APP), "--collect-data", "customtkinter",
        "--collect-submodules", "comtypes",  # UI Automation, for password-field detection
        "--add-data", f"{typing_data / 'words_en.txt'}{os.pathsep}predictive",
        "--add-data", f"{typing_data / 'modes'}{os.pathsep}predictive/modes",
        "--distpath", str(WORK / "pyinstaller-dist"), "--workpath", str(WORK / "pyinstaller"),
        "--specpath", str(WORK), str(APP / "app.py"),
    ], check=True)
    folder = WORK / "pyinstaller-dist" / "Hotk33"
    shutil.copy(ROOT / "README.md", folder / "README.md")
    shutil.copy(ROOT / "LICENSE", folder / "LICENSE.txt")
    zip_base = DIST / f"Hotk33-{__version__}-windows-x64"
    return Path(shutil.make_archive(str(zip_base), "zip", folder.parent, folder.name))


def build_firmware():
    sketch = ROOT / "firmware" / "Model100"
    out = ROOT / "firmware" / "build"
    if ARDUINO_CLI.exists():
        subprocess.run([str(ARDUINO_CLI), "compile", "--fqbn", FQBN, "--output-dir", str(out),
                        str(sketch)], check=True)
    else:
        print("arduino-cli not found - using the existing firmware build")
    target = DIST / f"Model100-MusicLEDs-{__version__}.bin"
    shutil.copy(out / "Model100.ino.bin", target)
    return target


if __name__ == "__main__":
    DIST.mkdir(exist_ok=True)
    for path in (build_app(), build_firmware()):
        print(f"built {path.relative_to(ROOT)}  ({path.stat().st_size / 1e6:.1f} MB)")
