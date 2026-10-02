"""Painted patterns: what each LED of a device shows, how a brush changes it,
and how a pattern is rendered (animations and the keypress heatmap).

Every LED has its own color, animation, intensity, heatmap reaction (its own
key heats it up when pressed) and reactivity: it can also react to every
keystroke (a ripple out from the key pressed) or to audio (the spectrum, from
the speakers or a microphone). A
brush paints them onto the LEDs around the one it's centered on: `size` LEDs
across, as a square or a circle. `weight` is how strongly the LEDs away from
the center take the brush: at 1 they all get it fully, lower values fade it
out toward the edge of the brush (the center always gets it fully).
"""

import numpy as np

ANIMATIONS = ["Static", "Breathe", "Blink", "Wave", "Rainbow", "Sparkle"]
REACTS = ["Nothing", "Keystrokes", "Audio"]
NOTHING, KEYSTROKES, AUDIO = range(3)
SQUARE, CIRCLE = "Square", "Circle"
# A key pressed with full reaction adds this much heat (heat 1 = hottest color).
HEAT_PER_PRESS = 0.35
MAX_HEAT = 1.5
# Keystroke reaction: a flash that fades over PULSE_S, spreading this fast.
PULSE_S = 0.35
RIPPLE_S_PER_KEY = 0.045
# Heat colors from warm to white-hot.
_HEAT_STOPS = np.array([(255, 40, 0), (255, 140, 0), (255, 230, 60), (255, 255, 255)]) / 255.0


class Brush:
    def __init__(self, color=(1.0, 1.0, 1.0), animation=0, intensity=1.0, reaction=0.0,
                 react=NOTHING, reactivity=0.6, size=1, shape=CIRCLE, weight=1.0):
        self.color = np.asarray(color, dtype=float)
        self.animation = animation
        self.intensity = intensity
        self.reaction = reaction
        self.react = react
        self.reactivity = reactivity
        self.size = size
        self.shape = shape
        self.weight = weight


class Pattern:
    """Per-LED paint of one device. Arrays are edited in place on the UI thread
    and read by the render thread; a frame drawn mid-stroke just shows part of it."""

    def __init__(self, n):
        self.n = n
        self.color = np.zeros((n, 3))           # 0..1
        self.animation = np.zeros(n, dtype=int)  # index into ANIMATIONS
        self.intensity = np.zeros(n)            # 0..1 (0 = off)
        self.reaction = np.zeros(n)             # 0..1, heat added per key press
        self.react = np.zeros(n, dtype=int)      # index into REACTS
        self.reactivity = np.zeros(n)           # 0..1, how much it reacts

    @property
    def empty(self):
        return not (self.intensity.any() or self.reaction.any())

    def uses(self, react):
        """Whether any lit LED reacts to `react` (KEYSTROKES or AUDIO)."""
        return bool(((self.react == react) & (self.reactivity > 0) & (self.intensity > 0)).any())

    def copy(self):
        p = Pattern(self.n)
        p.color[:], p.animation[:] = self.color, self.animation
        p.intensity[:], p.reaction[:] = self.intensity, self.reaction
        p.react[:], p.reactivity[:] = self.react, self.reactivity
        return p

    def paint(self, indices, strengths, brush):
        """Blends the brush into the LEDs at `indices`, each by its strength (0..1)."""
        s = np.asarray(strengths, dtype=float)
        idx = np.asarray(indices, dtype=int)
        self.color[idx] += (brush.color - self.color[idx]) * s[:, None]
        self.intensity[idx] += (brush.intensity - self.intensity[idx]) * s
        self.reaction[idx] += (brush.reaction - self.reaction[idx]) * s
        self.reactivity[idx] += (brush.reactivity - self.reactivity[idx]) * s
        strong = idx[s >= 0.5]
        self.animation[strong] = brush.animation
        self.react[strong] = brush.react

    def erase(self, indices, strengths):
        s = np.asarray(strengths, dtype=float)
        idx = np.asarray(indices, dtype=int)
        self.intensity[idx] *= 1 - s
        self.reaction[idx] *= 1 - s
        self.reactivity[idx] *= 1 - s
        gone = idx[s >= 0.5]
        self.color[gone], self.animation[gone], self.react[gone] = 0, 0, NOTHING

    def pick(self, i):
        """A brush that paints like LED i (size, shape and weight are left default)."""
        return Brush(self.color[i].copy(), int(self.animation[i]), float(self.intensity[i]),
                     float(self.reaction[i]), int(self.react[i]), float(self.reactivity[i]))

    # -- saving

    def to_json(self):
        return {
            "color": ["#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c) for c in self.color],
            "animation": [ANIMATIONS[a] for a in self.animation],
            "intensity": [int(round(v * 100)) for v in self.intensity],
            "reaction": [int(round(v * 100)) for v in self.reaction],
            "react": [REACTS[r] for r in self.react],
            "reactivity": [int(round(v * 100)) for v in self.reactivity],
        }

    @classmethod
    def from_json(cls, data, n):
        """Reads a saved pattern for a device with n LEDs (extra LEDs are cut,
        missing ones stay off). Raises ValueError/KeyError/TypeError if damaged."""
        p = cls(n)
        m = min(n, len(data["color"]))
        p.color[:m] = [[int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)] for c in data["color"][:m]]
        p.animation[:m] = [ANIMATIONS.index(a) if a in ANIMATIONS else 0
                           for a in data["animation"][:m]]
        p.intensity[:m] = np.clip(np.asarray(data["intensity"][:m], dtype=float) / 100, 0, 1)
        p.reaction[:m] = np.clip(np.asarray(data["reaction"][:m], dtype=float) / 100, 0, 1)
        react = data.get("react", [])[:m]
        p.react[:len(react)] = [REACTS.index(r) if r in REACTS else NOTHING for r in react]
        reactivity = data.get("reactivity", [])[:m]
        p.reactivity[:len(reactivity)] = np.clip(np.asarray(reactivity, dtype=float) / 100, 0, 1)
        return p


# ---------------------------------------------------------------- brush footprint

def centers(lay):
    """LED centers in layout units. Strip-only layouts (wrapped into rows for
    display) are measured along the strip instead."""
    if lay.round:
        return np.stack([np.arange(lay.n, dtype=float), np.zeros(lay.n)], axis=1)
    return np.array([(x + w / 2, y + h / 2) for x, y, w, h in lay.rects], dtype=float)


def footprint(lay, center, size, shape, weight):
    """(indices, strengths) of the LEDs a brush centered on LED `center` covers."""
    pts = centers(lay)
    d = pts - pts[center]
    half = (size - 1) / 2
    if shape == SQUARE:
        dist = np.abs(d).max(axis=1)
        reach = half + 0.3
    else:
        dist = np.hypot(d[:, 0], d[:, 1])
        reach = half + 0.5
    idx = np.nonzero(dist <= reach)[0]
    rel = np.clip(dist[idx] / max(half, 1e-6), 0, 1) if half > 0 else np.zeros(len(idx))
    strengths = 1 - (1 - weight) * rel
    strengths[idx == center] = 1.0
    return idx, strengths


# ---------------------------------------------------------------- rendering

def _hsv(h):
    """Fully saturated colors for hues h (0..1)."""
    h6 = (np.asarray(h) % 1.0) * 6
    return np.clip(np.stack([np.abs(h6 - 3) - 1, 2 - np.abs(h6 - 2), 2 - np.abs(h6 - 4)],
                            axis=-1), 0, 1)


def heat_color(h):
    h = np.clip(h, 0, 1)
    pos = np.linspace(0, 1, len(_HEAT_STOPS))
    return np.stack([np.interp(h, pos, _HEAT_STOPS[:, i]) for i in range(3)], axis=-1)


def ripple(lay, presses, now):
    """Per-LED keystroke pulse 0..1: each press [(time, center LED or None)]
    flashes the LEDs, spreading out from the key pressed (everywhere at once
    when the key isn't on this device)."""
    pulse = np.zeros(lay.n)
    if not presses:
        return pulse
    pts = centers(lay)
    for t, center in presses:
        age = now - t
        if center is None or center >= lay.n:
            delay = np.zeros(lay.n)
        else:
            delay = np.hypot(*(pts - pts[center]).T) * RIPPLE_S_PER_KEY
        a = age - delay
        pulse = np.maximum(pulse, np.where(a >= 0, np.exp(-np.maximum(a, 0) / PULSE_S), 0))
    return pulse


def render(pattern, lay, t, period, heat=None, pulse=None, bands=None):
    """The pattern at time t (s) as (n, 3) float RGB 0..1. period: seconds per
    animation cycle. heat: optional per-LED heat from key presses. pulse:
    per-LED keystroke pulse (ripple()). bands: audio band levels 0..1."""
    a = pattern.animation
    phase = t / period
    xs = lay.xs if lay.n == pattern.n else np.linspace(0, 1, pattern.n)
    level = np.ones(pattern.n)
    wave = 0.5 + 0.5 * np.sin(2 * np.pi * phase)
    level[a == 1] = 0.2 + 0.8 * wave                                       # Breathe
    level[a == 2] = 1.0 if phase % 1 < 0.5 else 0.08                      # Blink
    sel = a == 3                                                            # Wave
    level[sel] = 0.15 + 0.85 * (0.5 + 0.5 * np.sin(2 * np.pi * (phase - xs[sel])))
    sel = a == 5                                                            # Sparkle
    if sel.any():
        i = np.nonzero(sel)[0]
        seed = (np.sin(i * 12.9898) * 43758.5453) % 1
        level[sel] = 0.15 + 0.85 * np.maximum(0, np.sin(2 * np.pi * (phase * (1.2 + seed)
                                                                      + seed))) ** 6
    color = pattern.color.copy()
    sel = a == 4                                                            # Rainbow
    color[sel] = _hsv(phase + xs[sel] * 0.8)
    # reacting LEDs rest at (1 - reactivity) and light up with what they react to
    r = pattern.reactivity
    sel = (pattern.react == KEYSTROKES) & (r > 0)
    if sel.any():
        p = pulse[sel] if pulse is not None and len(pulse) == pattern.n else 0.0
        level[sel] *= 1 - r[sel] + r[sel] * p
    sel = (pattern.react == AUDIO) & (r > 0)
    if sel.any():
        if bands is not None and len(bands):
            b = np.minimum((xs[sel] * len(bands)).astype(int), len(bands) - 1)
            level[sel] *= 1 - r[sel] + r[sel] * np.asarray(bands)[b]
        else:
            level[sel] *= 1 - r[sel]
    out = color * (level * pattern.intensity)[:, None]
    if heat is not None and heat.any():
        h = np.clip(heat, 0, 1)
        out = out * (1 - h[:, None]) + heat_color(h) * h[:, None]
    return np.clip(out, 0, 1)
