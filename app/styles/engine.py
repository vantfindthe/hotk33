"""Styles mode's render loops, built on Paint mode's: one draws a catalog
style on every enabled device, the other shows a layout saved in Paint."""

import numpy as np

from paint.engine import PaintEngine
from .catalog import Context

HEATMAP_FADE_S = 2.5


def speed_factor(speed):
    """Speed setting 1..100 -> time multiplier (50 = 1x, 0.25x .. 4x)."""
    return 2 ** ((speed - 50) / 25)


def brightness(settings):
    return settings["style_brightness"] / 100


class StyleEngine(PaintEngine):
    """Draws `style` (catalog.Style) on every enabled device. `style` can be
    changed any time."""

    def __init__(self, outputs, style, settings):
        super().__init__(outputs, lambda out: None, settings)
        self.style = style

    def scene(self, devices):
        return {d.id: self.style for d in devices if d.layout is not None}

    def lit(self, source):
        return True

    def wants_audio(self, scene):
        return False

    def reaction_of(self, out):
        if out.layout is None or not self.style.reactive:
            return None
        return np.ones(out.layout.n)

    def heat_fade(self):
        return HEATMAP_FADE_S

    def draw(self, out, style, t, now, heat, presses, bands):
        s = self.settings
        ctx = Context(out.layout, t * speed_factor(s["style_speed"]),
                      np.array(s["style_color"]) / 255, heat,
                      [(now - pt, center) for pt, center in presses])
        return style.render(ctx) * brightness(s)


class LayoutEngine(PaintEngine):
    """A layout saved in Paint mode, at the Styles brightness."""

    def draw(self, out, source, t, now, heat, presses, bands):
        return super().draw(out, source, t, now, heat, presses, bands) * brightness(self.settings)
