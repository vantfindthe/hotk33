"""The graphic equalizer for per-band sensitivity."""

import tkinter as tk
from tkinter import font as tkfont

import numpy as np

from widgets import ACCENT, CARD, FAINT, FONT, MUTED, TRACK, rgb01, rounded_points, to_hex
from . import audio


class Equalizer(tk.Canvas):
    """Graphic EQ: one column per band, with a live level meter behind a
    draggable gain handle. Drag across columns to paint a curve,
    double-click to zero a band, scroll to nudge it by 1 dB."""

    def __init__(self, master, gains, range_db, scale, on_change=None, **kw):
        super().__init__(master, bg=CARD, highlightthickness=0, cursor="hand2", **kw)
        self.gains = gains  # list of ints, edited in place
        self.range_db = range_db
        self.scale = scale
        self.on_change = on_change
        self.levels = np.zeros(audio.NUM_BANDS)
        self.band_colors = np.tile(rgb01(ACCENT), (audio.NUM_BANDS, 1))
        self._last_col = None
        self.meters, self.handles, self.values = [], [], []  # created in _layout()
        self.font_small = tkfont.Font(family=FONT, size=-round(11 * scale))
        self.font_value = tkfont.Font(family=FONT, size=-round(11 * scale), weight="bold")
        self.bind("<Configure>", lambda e: self._layout())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_last_col", None))
        self.bind("<Double-Button-1>", self._reset_band)
        self.bind("<MouseWheel>", self._wheel)

    # geometry -----------------------------------------------------------

    def _layout(self):
        self.delete("all")
        sc = self.scale
        w, h = self.winfo_width(), self.winfo_height()
        self.x0, self.x1 = 40 * sc, w - 8 * sc
        self.y0, self.y1 = 10 * sc, h - 40 * sc
        self.col_w = (self.x1 - self.x0) / audio.NUM_BANDS
        self.bar_w = min(self.col_w * 0.55, 30 * sc)
        mid = self._gain_y(0)

        for db in (self.range_db, 0, -self.range_db):
            self.create_text(self.x0 - 10 * sc, self._gain_y(db), text=f"{db:+d}" if db else "0 dB",
                             anchor="e", fill=FAINT, font=self.font_small)
        self.create_line(self.x0, mid, self.x1, mid, fill="#343442", dash=(2, 4))

        self.meters, self.handles, self.values = [], [], []
        for i, fc in enumerate(audio.band_centers()):
            cx = self._cx(i)
            bw = self.bar_w / 2
            self.create_polygon(rounded_points(cx - bw, self.y0, cx + bw, self.y1, bw),
                                smooth=True, fill=TRACK, outline="")
            self.meters.append(self.create_polygon(0, 0, 0, 0, 0, 0, smooth=True, outline=""))
            label = f"{fc / 1000:.1f}k" if 1000 <= fc < 10000 else (
                f"{fc / 1000:.0f}k" if fc >= 10000 else f"{fc:.0f}")
            self.create_text(cx, self.y1 + 13 * sc, text=label, fill=MUTED, font=self.font_small)
            self.values.append(self.create_text(cx, self.y1 + 29 * sc, font=self.font_value))

        self.curve = self.create_line(0, 0, 0, 0, fill=ACCENT, width=max(2, round(2 * sc)),
                                      smooth=True, capstyle="round")
        r = 6.5 * sc
        for i in range(audio.NUM_BANDS):
            self.handles.append(self.create_oval(0, 0, r, r, fill="#f4f4f8", outline=ACCENT,
                                                 width=max(2, round(2 * sc))))
        self._draw_gains()
        self.set_levels(self.levels, self.band_colors)

    def _cx(self, i):
        return self.x0 + (i + 0.5) * self.col_w

    def _gain_y(self, db):
        mid, half = (self.y0 + self.y1) / 2, (self.y1 - self.y0) / 2 - 7 * self.scale
        return mid - db / self.range_db * half

    def _y_gain(self, y):
        mid, half = (self.y0 + self.y1) / 2, (self.y1 - self.y0) / 2 - 7 * self.scale
        db = round((mid - y) / half * self.range_db)
        db = max(-self.range_db, min(self.range_db, db))
        return 0 if abs(db) <= 1 else db

    # drawing ------------------------------------------------------------

    def _draw_gains(self):
        if not self.handles:
            return
        r = 6.5 * self.scale
        pts = []
        for i, g in enumerate(self.gains):
            cx, cy = self._cx(i), self._gain_y(g)
            pts += [cx, cy]
            self.coords(self.handles[i], cx - r, cy - r, cx + r, cy + r)
            self.itemconfigure(self.values[i], text=f"{g:+d}" if g else "0",
                               fill=ACCENT if g else FAINT)
        self.coords(self.curve, *pts)

    def set_levels(self, levels, band_colors):
        self.levels, self.band_colors = levels, band_colors
        if not self.meters:
            return
        track = rgb01(TRACK)
        bw = self.bar_w / 2
        for i, (m, level) in enumerate(zip(self.meters, levels)):
            cx = self._cx(i)
            top = self.y1 - float(level) * (self.y1 - self.y0)
            if level < 0.01:
                self.coords(m, 0, 0, 0, 0, 0, 0)
                continue
            self.coords(m, *rounded_points(cx - bw, top, cx + bw, self.y1, bw))
            self.itemconfigure(m, fill=to_hex(track + (band_colors[i] - track) * 0.7))

    # interaction ----------------------------------------------------------

    def _col(self, x):
        return max(0, min(audio.NUM_BANDS - 1, int((x - self.x0) // self.col_w)))

    def _set(self, i, db):
        if self.gains[i] != db:
            self.gains[i] = db
            if self.on_change:
                self.on_change()

    def _press(self, e):
        self._last_col = self._col(e.x)
        self._set(self._last_col, self._y_gain(e.y))
        self._draw_gains()

    def _drag(self, e):
        col, db = self._col(e.x), self._y_gain(e.y)
        last = self._last_col if self._last_col is not None else col
        step = 1 if col >= last else -1
        for i in range(last, col + step, step):  # fill columns skipped by a fast drag
            self._set(i, db)
        self._last_col = col
        self._draw_gains()

    def _reset_band(self, e):
        self._set(self._col(e.x), 0)
        self._draw_gains()

    def _wheel(self, e):
        i = self._col(e.x)
        db = self.gains[i] + (1 if e.delta > 0 else -1)
        self._set(i, max(-self.range_db, min(self.range_db, db)))
        self._draw_gains()

    def redraw(self):
        self._draw_gains()
