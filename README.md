# Predictive Key Lights

Your keyboard shows you what you're about to type. After every key press,
the key you're most likely to press next lights up **green**, the second most
likely **yellow**, and the third **red**. Every other key goes dark. It works
in any app on Windows, and it knows whether you're writing English, Python,
JavaScript or a PowerShell, cmd or bash command.

![English: after "over th", E is green, I yellow, A red](docs/english.png)

Type `t` and **H** lights up (then **O**, **R**). Type `th` and you get **E**,
**A**, **I**. After `the` it's **Space**.

## Modes

| | |
|---|---|
| ![Python mode](docs/python.png) | ![PowerShell mode](docs/powershell.png) |
| Python in VS Code: after `os.list` comes **D** (`listdir`) | PowerShell in Windows Terminal: `-fi` → **L** (`-Filter`) |

| Mode | Predicts from | Picked automatically when you type in |
|---|---|---|
| English | 59,000-word frequency list ([wordfreq](https://github.com/rspeer/wordfreq)) | anything else |
| Python | the Python standard library | an editor or IDE with a `.py` file in its title |
| JavaScript / TypeScript | Node.js and npm sources | `.js .mjs .cjs .jsx .ts .tsx` |
| PowerShell | Windows PowerShell modules and common commands | `powershell`, `pwsh`, PowerShell tabs in Windows Terminal (and unknown terminals) |
| Command Prompt | `.bat`/`.cmd` files and common commands | `cmd.exe`, Command Prompt tabs |
| Bash / Git Bash / WSL | Git for Windows shell scripts and common commands | Git Bash (mintty), `wsl`, `bash`, tabs titled `MINGW64`, `user@host:~` ... |

**Auto** (the default) follows the window you're typing in. Pick a mode in the
drop-down to fix it. In code and terminal modes **Enter** can light up too,
and pressing it carries the context to the next line.

## It learns how you type

English learns your words and which word you type after which. Code and
terminal modes learn your names (identifiers, commands) and your
character patterns. What you type is mixed in by confidence, so a word or
pattern you've used once or twice already shows up. Type "hi claude" once and
`hi ` lights **C** next time.

The **Learning** card counts what each mode has picked up. It stays in
memory unless **Remember between sessions** is on. Then it's saved (every
minute and on close) to `%APPDATA%\PredictiveKeyLights\learned.json`, on your
PC only. **Forget everything learned** wipes it.

## Passwords and private mode

![Private mode](docs/private.png)

- **Password fields are skipped automatically.** This covers browsers, most
  apps, Windows sign-in prompts and classic password boxes (it uses Windows UI
  Automation). Keystrokes there aren't recorded or learned, the context around
  them is dropped, and every key goes dark so the lights give nothing away.
- **Private mode, `Ctrl+Alt+P`**, does the same by hand, from anywhere, for
  prompts Windows can't see as password fields: `sudo`, `ssh`,
  `Read-Host -AsSecureString`, a password typed into a chat... Press it before
  typing and again after. A rising beep means private, a falling beep means
  back to normal. The hotkey itself is never passed on to the app you're in.
  Change it with `private_hotkey` in the settings, e.g. `"ctrl+shift+f12"`.

**Show typed text** (on by default) shows what you typed in the window. Turn
it off if people can see your screen.

## Keyboards

| Brand | How | You need |
|---|---|---|
| **Logitech G** (G610 tested) | G HUB LED SDK | G HUB running. White-only boards (G610, G710) show the 3 guesses as bright, medium and dim |
| **Razer** (BlackWidow, Huntsman, Ornata, ...) | Chroma SDK | Razer Synapse with Chroma Connect |
| **SteelSeries** (Apex, ...) | GameSense | SteelSeries GG (Engine) running |
| **Keychron** (Q, V, K Max/Pro/HE, ...) | OpenRGB | [OpenRGB 1.0+](https://openrgb.org) with the **SDK Server** started, Keychron firmware 1.1.1+, **USB cable** (not Bluetooth / 2.4 GHz) |
| **Keyboardio Model 100** | Focus serial | the MusicLEDs firmware from [rgb-music-visualizer](https://github.com/vantfindthe/rgb-music-visualizer); Chrysalis closed |
| **Corsair, HyperX, ASUS, Wooting, other QMK/VialRGB** | OpenRGB | OpenRGB with the SDK Server started (and the vendor app closed) |

Keyboards are found automatically (**Rescan** checks again). When a keyboard is
plugged in but can't be lit yet, it's still listed, marked **needs setup**,
with what to do. For example, start Synapse, or connect the Keychron with a
cable.

Notes:
- Only the Logitech G610 has been tested with this app on real hardware (the
  Model 100 driver is the one used in rgb-music-visualizer). The Razer,
  SteelSeries and OpenRGB drivers are tested against simulated services.
  Reports welcome.
- Key positions assume a US layout (and the default QWERTY layer on the Model 100).
- Don't let two programs drive the same keyboard, for example a Razer board through
  both Synapse and OpenRGB, or this together with rgb-music-visualizer.
- Keychron boards on older firmware, or connected wirelessly, can't set
  individual keys from a PC.

## Install

Needs Windows 10/11 and [Python 3.12](https://www.python.org/downloads/).

```bat
git clone https://github.com/vantfindthe/predictive-key-lights
cd predictive-key-lights
setup.bat
```

Then start it with `KeyLights.bat`. The models are included; no internet
connection is needed after setup.

## Settings

`%APPDATA%\PredictiveKeyLights\settings.json`:

| Setting | Default | |
|---|---|---|
| `colors` | green, yellow, red | RGB for the 1st, 2nd and 3rd guess |
| `white_levels` | `[255, 80, 18]` | brightness per guess on white-only keyboards |
| `private_hotkey` | `"ctrl+alt+p"` | modifiers (`ctrl alt shift win`) + a letter, digit, `f1`-`f24`, `pause`, `scrolllock`, `insert` or `space` |
| `hotkey_sound` | `true` | beep when private mode switches |
| `idle_release_s` | `0` | hand the keyboards their own lighting back after this many idle seconds (0 = never) |

## Training on your own code or shell history

```bat
.venv\Scripts\python tools\build_modes.py python --extra D:\src\my-project
.venv\Scripts\python tools\build_modes.py powershell bash --history
.venv\Scripts\python tools\build_modes.py rust --new "Rust" .rs D:\src\some-rust-repo
```

- `--extra` adds your own code to a mode.
- `--history` trains the terminal modes on your PowerShell or bash command
  history, which is the best data for them. The model then holds fragments of
  that history, so don't share the `.json.gz` it writes.
- `--new` adds a language. Auto then picks it up by file extension.

Restart the app after rebuilding.

## How it works

| Path | What |
|---|---|
| `app/app.py` | window (CustomTkinter) |
| `app/engine.py` | keystrokes -> context -> predictions -> frames; one sender thread for all keyboards |
| `app/hook.py` | system-wide keyboard hook (read-only, except the private-mode hotkey) |
| `app/predict.py` | English word model, code/terminal character n-gram models, learning |
| `app/modes.py` | Auto mode: which mode fits the focused window |
| `app/secure.py` | password-field detection (UI Automation + Win32) |
| `app/devices/` | one module per keyboard backend, plus connected-keyboard detection |
| `tools/build_modes.py`, `tools/seeds/` | trains the code and terminal models |
| `tools/build_wordlist.py` | regenerates the English word list |
| `tools/screenshots.py` | renders the screenshots above (scripted, no real typing) |

English prediction: every word that starts with what you've typed votes for
its next letter, weighted by how common it is. A finished word votes for space
and punctuation. A letter-trigram model covers names and typos. Code and
terminal modes use a 7-character n-gram model (trained with indentation
stripped, since editors insert it) blended with completion from the mode's
vocabulary.

## License

GPL-3.0. See [LICENSE](LICENSE). The keyboard drivers come from
[rgb-music-visualizer](https://github.com/vantfindthe/rgb-music-visualizer).
