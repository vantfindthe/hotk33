"""Key ids, and the characters each key types.

A key is identified by the character it types without Shift (US layout), or
"space". Predictions are characters, so char_key() finds the key to light.
"""

# Unshifted character -> shifted character (US layout).
SHIFTED = dict(zip("`1234567890-=[]\\;',./", '~!@#$%^&*()_+{}|:"<>?'))
UNSHIFT = {v: k for k, v in SHIFTED.items()}

ROWS = [
    "`1234567890-=",
    "qwertyuiop[]\\",
    "asdfghjkl;'",
    "zxcvbnm,./",
]
TYPING_KEYS = [k for row in ROWS for k in row] + ["space", "enter"]

# Where each typing key sits on a US keyboard, in key units (1 = a key plus
# the gap to the next one): key id -> (x, y, w, h).
ROW_OFFSETS = [0, 0.6, 0.85, 1.3]
WIDTH = 14.55
POSITIONS = {key: (ROW_OFFSETS[r] + c, r, 1, 1) for r, row in enumerate(ROWS)
             for c, key in enumerate(row)}
POSITIONS["space"] = (3.3, 4, 6.2, 1)
POSITIONS["enter"] = (ROW_OFFSETS[2] + len(ROWS[2]), 2,
                      WIDTH - ROW_OFFSETS[2] - len(ROWS[2]), 1)


def char_key(ch):
    """The key that types `ch` (with or without Shift), or None."""
    if ch == " ":
        return "space"
    if ch == "\n":
        return "enter"
    ch = ch.lower()
    ch = UNSHIFT.get(ch, ch)
    return ch if ch in TYPING_KEYS else None


def label(key):
    return {"space": "Space", "enter": "Enter"}.get(key, key.upper())


# Windows virtual-key codes of the typing keys (US layout).
VK = {0x20: "space"}
VK.update({0x30 + i: str(i) for i in range(10)})
VK.update({0x41 + i: chr(ord("a") + i) for i in range(26)})
VK.update({0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
           0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'"})
VK_NUMPAD = {0x60 + i: str(i) for i in range(10)}
VK_NUMPAD.update({0x6A: "*", 0x6B: "+", 0x6D: "-", 0x6E: ".", 0x6F: "/"})
