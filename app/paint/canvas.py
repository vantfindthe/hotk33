"""The device preview, made paintable: click or drag on it to paint, and the
keys the brush would cover are outlined under the mouse."""

import numpy as np

from widgets import DevicePreview

HOVER_OUTLINE = "#ffffff"


class PaintCanvas(DevicePreview):
    def __init__(self, master, on_stroke, on_paint, on_hover, **kw):
        """on_stroke(): a stroke starts (for undo). on_paint(led): paint at LED
        index `led`. on_hover(led or None) -> the LEDs to outline."""
        super().__init__(master, **kw)
        self.configure(cursor="crosshair")
        self.on_stroke, self.on_paint, self.on_hover = on_stroke, on_paint, on_hover
        self.hover = []
        self._outlined = []
        self._last = None
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_last", None))
        self.bind("<Motion>", self._move)
        self.bind("<Leave>", lambda e: self._set_hover(None))

    def led_at(self, x, y):
        """Index of the LED under canvas point (x, y), or None."""
        lay = self.layout
        if lay is None or not self.items:
            return None
        (ox, oy), s = self.origin, self.unit
        ux, uy = (x - ox) / s, (y - oy) / s
        rects = np.asarray(lay.rects, dtype=float)
        inside = np.nonzero((rects[:, 0] <= ux) & (ux <= rects[:, 0] + rects[:, 2])
                            & (rects[:, 1] <= uy) & (uy <= rects[:, 1] + rects[:, 3]))[0]
        if len(inside):
            return int(inside[0])
        cx, cy = rects[:, 0] + rects[:, 2] / 2, rects[:, 1] + rects[:, 3] / 2
        d = np.hypot(cx - ux, cy - uy)
        i = int(d.argmin())
        return i if d[i] < 0.75 else None

    def _press(self, e):
        led = self.led_at(e.x, e.y)
        if led is None:
            return
        self.on_stroke()
        self._last = led
        self.on_paint(led)

    def _drag(self, e):
        led = self.led_at(e.x, e.y)
        self._set_hover(led)
        if led is not None and led != self._last:  # each key once as the brush passes
            self._last = led
            self.on_paint(led)

    def _move(self, e):
        self._set_hover(self.led_at(e.x, e.y))

    def _set_hover(self, led):
        self.hover = list(self.on_hover(led)) if led is not None else []
        self.show(self.colors)

    def show(self, colors):
        super().show(colors)
        if colors is None or len(colors) != len(self.items):
            return
        for i in self._outlined:
            if i < len(self.items):
                self.itemconfigure(self.items[i][1], width=1)
        self._outlined = [i for i in self.hover if i < len(self.items)]
        for i in self._outlined:
            self.itemconfigure(self.items[i][1], outline=HOVER_OUTLINE, width=2)

    def _layout(self):
        self._outlined = []
        super()._layout()
