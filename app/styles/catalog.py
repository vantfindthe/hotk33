"""Ready-made lighting styles, modeled on the RGB Matrix effects Keychron's
Launcher (and QMK) offer.

Each style renders a whole device from its LED positions (layout xs/ys, 0..1),
the time, the chosen color and the key presses. Styles that react to typing
need the keyboard hook while they run.
"""

import colorsys

import numpy as np

from paint.pattern import centers, heat_color


class Context:
    """What a style draws from.

    lay      the device's layout
    t        seconds, already scaled by the speed setting
    color    chosen color, RGB 0..1; hue is its hue (0..1)
    heat     per-LED heat from key presses (Typing heatmap), or None
    presses  [(age in s, center LED or None)]; None = pressed somewhere the
             lights mustn't show (a password field) or off this device
    """

    def __init__(self, lay, t, color, heat=None, presses=()):
        self.lay, self.t, self.color = lay, t, np.asarray(color, dtype=float)
        self.hue = colorsys.rgb_to_hsv(*self.color)[0]
        self.heat = heat
        self.presses = list(presses)
        self.xs, self.ys = lay.xs, lay.ys
        self.n = lay.n

    def solid(self, level=1.0):
        return self.color[None, :] * np.broadcast_to(np.asarray(level, float), (self.n,))[:, None]

    def dist_center(self):
        return np.hypot(self.xs - 0.5, (self.ys - 0.5) * 0.5) * 1.6

    def angle(self):
        return (np.arctan2((self.ys - 0.5) * 0.5, self.xs - 0.5) / (2 * np.pi)) % 1.0


def hsv(h, s=1.0, v=1.0):
    """Colors for hues h (0..1) at saturation s and value v (arrays or scalars)."""
    h6 = (np.asarray(h, dtype=float) % 1.0) * 6
    rgb = np.clip(np.stack([np.abs(h6 - 3) - 1, 2 - np.abs(h6 - 2), 2 - np.abs(h6 - 4)],
                           axis=-1), 0, 1)
    s = np.asarray(s, dtype=float)[..., None] if np.ndim(s) else s
    v = np.asarray(v, dtype=float)[..., None] if np.ndim(v) else v
    return (1 - s + rgb * s) * v


def _hash(a, b=0.0):
    """Repeatable pseudo-random numbers 0..1."""
    return (np.sin(np.asarray(a, dtype=float) * 12.9898 + np.asarray(b, dtype=float) * 78.233)
            * 43758.5453) % 1.0


def _slots(ctx, rate):
    """Per LED: which random time slot it's in, and how far through it (0..1)."""
    i = np.arange(ctx.n)
    pos = ctx.t * rate + _hash(i, 7.0)
    return i, np.floor(pos), pos % 1.0


# ---------------------------------------------------------------- styles

def solid(ctx):
    return ctx.solid()


def breathing(ctx):
    return ctx.solid(0.12 + 0.88 * (0.5 + 0.5 * np.sin(2 * np.pi * ctx.t / 3)))


def cycle_all(ctx):
    return np.tile(hsv(ctx.hue + ctx.t * 0.08), (ctx.n, 1))


def cycle_left_right(ctx):
    return hsv(ctx.hue + ctx.xs - ctx.t * 0.15)


def cycle_up_down(ctx):
    return hsv(ctx.hue + ctx.ys * 0.6 - ctx.t * 0.15)


def cycle_out_in(ctx):
    return hsv(ctx.hue + ctx.dist_center() + ctx.t * 0.15)


def chevron(ctx):
    return hsv(ctx.hue + ctx.xs + np.abs(ctx.ys - 0.5) * 0.6 - ctx.t * 0.15)


def pinwheel(ctx):
    return hsv(ctx.hue + ctx.angle() + ctx.t * 0.1)


def spiral(ctx):
    return hsv(ctx.hue + ctx.angle() + ctx.dist_center() * 1.5 - ctx.t * 0.15)


def gradient_left_right(ctx):
    return hsv(ctx.hue + ctx.xs * 0.33)


def gradient_up_down(ctx):
    return hsv(ctx.hue + ctx.ys * 0.33)


def jellybean(ctx):
    i, slot, frac = _slots(ctx, 0.5)
    return hsv(_hash(i, slot), 1.0, np.sin(np.pi * frac) ** 2)


def pixel_rain(ctx):
    i, slot, frac = _slots(ctx, 0.35)
    on = _hash(i, slot + 0.5) < 0.3
    hue = ctx.hue + (_hash(i, slot + 0.25) - 0.5) * 0.3
    return hsv(hue, 1.0, np.where(on, np.sin(np.pi * frac), 0.0))


def digital_rain(ctx):
    col = np.round(ctx.xs * 30)
    speed = 0.25 + 0.35 * _hash(col, 3.0)
    head = (ctx.t * speed + _hash(col, 9.0)) % 1.0 * 1.6 - 0.2
    behind = head - ctx.ys
    level = np.where(behind >= 0, np.exp(-behind * 6), 0.0)
    white = np.clip((level - 0.8) * 4, 0, 1)
    green = np.array([0.1, 1.0, 0.25])
    return level[:, None] * (green * (1 - white[:, None]) + white[:, None])


def starlight(ctx):
    i = np.arange(ctx.n)
    twinkle = np.maximum(0, np.sin(2 * np.pi * (ctx.t * (0.15 + 0.3 * _hash(i, 1.0))
                                                 + _hash(i, 2.0)))) ** 10
    hue = ctx.hue + (_hash(i, 4.0) - 0.5) * 0.15
    return hsv(hue, 0.8, 0.08 + 0.92 * twinkle)


def typing_heatmap(ctx):
    if ctx.heat is None:
        return np.zeros((ctx.n, 3))
    h = np.clip(ctx.heat, 0, 1)
    return heat_color(h) * np.clip(h * 1.5, 0, 1)[:, None]


def reactive(ctx):
    level = np.zeros(ctx.n)
    for age, center in ctx.presses:
        if center is not None and center < ctx.n:
            level[center] = max(level[center], np.exp(-age / 0.6))
    return ctx.solid(level)


def _rings(ctx, colors_fn):
    pts = centers(ctx.lay)
    out = np.zeros((ctx.n, 3))
    for age, center in ctx.presses:
        if center is None or center >= ctx.n or age > 2.5:
            continue
        dist = np.hypot(*(pts - pts[center]).T)
        ring = np.exp(-((dist - age * 9) ** 2) / 1.2) * np.exp(-age / 0.9)
        out = np.maximum(out, colors_fn(dist) * ring[:, None])
    return out


def splash(ctx):
    return _rings(ctx, lambda dist: np.tile(ctx.color, (len(dist), 1)))


def multisplash(ctx):
    return _rings(ctx, lambda dist: hsv(ctx.hue + dist * 0.06))


class Style:
    def __init__(self, name, fn, desc, color=True, reactive=False):
        self.name, self.fn, self.desc = name, fn, desc
        self.uses_color = color  # the Color option changes it
        self.reactive = reactive  # reacts to typing: needs the keyboard hook

    def render(self, ctx):
        return np.clip(self.fn(ctx), 0, 1)


STYLES = [
    Style("Solid", solid, "One color on every key."),
    Style("Breathing", breathing, "The color slowly fades in and out."),
    Style("Cycle all", cycle_all, "Every key cycles through the rainbow together."),
    Style("Cycle left-right", cycle_left_right, "A rainbow wave moving across the keyboard."),
    Style("Cycle up-down", cycle_up_down, "A rainbow wave moving from top to bottom."),
    Style("Cycle out-in", cycle_out_in, "Rainbow rings moving in toward the center."),
    Style("Rainbow chevron", chevron, "A rainbow chevron sweeping across."),
    Style("Pinwheel", pinwheel, "A rainbow pinwheel turning around the center."),
    Style("Spiral", spiral, "A rainbow spiral turning around the center."),
    Style("Gradient left-right", gradient_left_right, "A still gradient from the color, "
                                                       "across the keyboard."),
    Style("Gradient up-down", gradient_up_down, "A still gradient from the color, top to "
                                                 "bottom."),
    Style("Jellybean raindrops", jellybean, "Keys fade in and out in random colors.",
          color=False),
    Style("Pixel rain", pixel_rain, "A few keys at a time light up around the color."),
    Style("Digital rain", digital_rain, "Green code raining down the columns.", color=False),
    Style("Starlight", starlight, "Keys twinkle like stars around the color."),
    Style("Typing heatmap", typing_heatmap, "Keys heat up the more you type them.",
          color=False, reactive=True),
    Style("Reactive", reactive, "Each key lights up as you press it, then fades.",
          reactive=True),
    Style("Splash", splash, "A ring of color spreads out from every key you press.",
          reactive=True),
    Style("Multisplash", multisplash, "Rainbow rings spread out from every key you press.",
          reactive=True),
]
BY_NAME = {s.name: s for s in STYLES}
