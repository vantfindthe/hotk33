"""LED effects.

Each frame the engine calls `update(analyzer)` once, then `render(layout, ...)`
for every device, which returns a (layout.n, 3) float array of RGB in 0..1.
Keys in a 2-D grid get the full effect; LEDs on strips (fans, ARGB, zones)
get a 1-D version of it.
"""

import colorsys
import time

import numpy as np

import layout as layouts

# Few-LED devices are rendered on this strip and averaged down (see render()).
VIRTUAL_STRIP = layouts.strip(16)


# ---------------------------------------------------------------- palettes

def _gradient(*stops):
    stops = np.array(stops, dtype=float) / 255.0
    pos = np.linspace(0, 1, len(stops))

    def fn(t):
        t = np.clip(np.asarray(t, dtype=float), 0, 1)
        return np.stack([np.interp(t, pos, stops[:, i]) for i in range(3)], axis=-1)
    return fn


def _rainbow(t):
    t = np.atleast_1d(np.asarray(t, dtype=float))
    return np.array([colorsys.hsv_to_rgb(h % 1.0, 1, 1) for h in t * 0.85])


PALETTES = {
    "Rainbow": _rainbow,
    "Fire": _gradient((255, 0, 0), (255, 60, 0), (255, 140, 0), (255, 220, 40)),
    "Ocean": _gradient((0, 20, 255), (0, 120, 255), (0, 230, 200), (180, 255, 255)),
    "Synthwave": _gradient((120, 0, 255), (255, 0, 180), (255, 60, 90), (0, 220, 255)),
    "Forest": _gradient((0, 120, 20), (60, 255, 0), (200, 255, 0), (255, 200, 0)),
    "Meter": _gradient((0, 255, 0), (160, 255, 0), (255, 200, 0), (255, 0, 0)),
}


def gradient_palette(stops):
    """A palette through the given colors (0..255 RGB), evenly spaced. One
    color is a solid palette."""
    if len(stops) == 1:
        return solid_palette(stops[0])
    return _gradient(*stops)


def solid_palette(rgb):
    color = np.array(rgb, dtype=float) / 255.0

    def fn(t):
        t = np.atleast_1d(np.asarray(t, dtype=float))
        return np.tile(color, (len(t), 1))
    return fn


# ---------------------------------------------------------------- helpers

def _band_levels(a, pos):
    band = np.minimum((pos * a.num_bands).astype(int), a.num_bands - 1)
    return a.bands[band]


def _fill(level, height):
    """How lit a key is when a bar of `level` fills the grid from the bottom."""
    return np.clip((level * 1.1 - height * 0.9) * 4, 0, 1)


def _summarize(colors, n):
    """Averages a strip down to n LEDs, keeping each segment's peak brightness."""
    out = []
    for seg in np.array_split(colors, n):
        mean = seg.mean(axis=0)
        peak = seg.max()
        out.append(mean * (peak / mean.max()) if mean.max() > 1e-6 else mean)
    return np.array(out)


def render(effect, lay, a, palette, spatial):
    if lay.tiny:
        return _summarize(effect.render(VIRTUAL_STRIP, a, palette, spatial), lay.n)
    return effect.render(lay, a, palette, spatial)


# ---------------------------------------------------------------- effects

class Effect:
    def update(self, a):
        pass

    def render(self, lay, a, palette, spatial):
        raise NotImplementedError


class SpectrumBars(Effect):
    """Each key column is a frequency band - bass on the left, treble on the right."""

    def render(self, lay, a, palette, spatial):
        level = _band_levels(a, lay.xs)
        lit = np.where(lay.linear, level, _fill(level, lay.height))
        t = lay.xs if spatial else np.where(lay.linear, level, lay.height)
        return palette(t) * lit[:, None]


class MirrorSpectrum(Effect):
    """Bass in the middle, treble toward the outer edges of both halves."""

    def render(self, lay, a, palette, spatial):
        dist = np.abs(lay.xs - 0.5) * 2  # 0 center .. 1 edge
        level = _band_levels(a, dist)
        lit = np.where(lay.linear, level, _fill(level, lay.height))
        t = dist if spatial else np.where(lay.linear, level, lay.height)
        return palette(t) * lit[:, None]


class SpectrumGlow(Effect):
    """Every key glows with the level of its column's frequency band."""

    def render(self, lay, a, palette, spatial):
        level = _band_levels(a, lay.xs)
        return palette(lay.xs if spatial else level) * level[:, None]


class BeatPulse(Effect):
    """The whole keyboard pulses with the bass and changes color on every beat."""

    def __init__(self):
        self.pos = 0.0
        self.env = 0.0

    def update(self, a):
        if a.beat:
            self.pos = (self.pos + 0.17) % 1.0
            self.env = 1.0
        self.env = max(self.env * 0.86, a.bass)

    def render(self, lay, a, palette, spatial):
        falloff = 1 - np.hypot(lay.xs - 0.5, (lay.ys - 0.5) * 0.6) * (1 - self.env)
        return palette(np.full(lay.n, self.pos)) * (self.env * falloff)[:, None]


class Ripples(Effect):
    """Every beat sends a ring of color rippling out from the center."""

    def __init__(self):
        self.rings = []  # (start_time, palette position)
        self.pos = 0.0

    def update(self, a):
        now = time.monotonic()
        if a.beat:
            self.pos = (self.pos + 0.13) % 1.0
            self.rings.append((now, self.pos))
        self.rings = [r for r in self.rings if now - r[0] < 1.2]

    def render(self, lay, a, palette, spatial):
        now = time.monotonic()
        level = _band_levels(a, lay.xs)
        out = palette(lay.xs if spatial else level) * (level * 0.2)[:, None]
        dist = np.hypot(lay.xs - 0.5, (lay.ys - 0.45) * 0.35)
        for start, pos in self.rings:
            age = now - start
            ring = np.clip(1 - np.abs(dist - age * 0.55) / 0.07, 0, 1) * (1 - age / 1.2)
            out = np.maximum(out, palette(np.full(lay.n, pos)) * ring[:, None])
        return out


class VUMeter(Effect):
    """A volume meter: the left half shows the left channel, the right half the right."""

    def render(self, lay, a, palette, spatial):
        grid_lit = _fill(np.where(lay.left, a.vu[0], a.vu[1]), lay.height)
        strip_lit = _fill(np.full(lay.n, a.vu.mean()), lay.xs)  # strips fill from the start
        lit = np.where(lay.linear, strip_lit, grid_lit)
        return palette(np.where(lay.linear, lay.xs, lay.height)) * lit[:, None]


EFFECTS = {
    "Bars": SpectrumBars,
    "Mirror": MirrorSpectrum,
    "Glow": SpectrumGlow,
    "Pulse": BeatPulse,
    "Ripples": Ripples,
    "VU meter": VUMeter,
}
