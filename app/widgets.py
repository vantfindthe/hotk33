"""Custom-drawn widgets and the color theme."""

import tkinter as tk
from tkinter import font as tkfont

import numpy as np
from PIL import Image, ImageDraw

# ---------------------------------------------------------------- theme

BG = "#0e0e13"
CARD = "#16161d"
CARD_BORDER = "#23232d"
STAGE = "#0a0a0e"
KEY_OFF = "#20202a"
KEY_OUTLINE = "#2b2b37"
TEXT = "#ececf1"
MUTED = "#8b8b9a"
FAINT = "#555563"
ACCENT = "#7c5cff"
ACCENT_HOVER = "#6947f5"
FIELD = "#1e1e27"
FIELD_HOVER = "#2a2a35"
TRACK = "#1f1f29"
GOOD, WARN, BAD, IDLE, INFO = "#4ade80", "#fbbf24", "#f87171", "#6b6b7b", "#7dd3fc"
FONT = "Segoe UI"
FONT_DISPLAY = "Segoe UI Variable Display"


def rgb01(hex_color):
    return np.array([int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]) / 255.0


def to_hex(rgb):
    r, g, b = (int(round(float(np.clip(c, 0, 1)) * 255)) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def rounded_points(x0, y0, x1, y1, r):
    """Polygon points for a rounded rectangle (draw with smooth=True)."""
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
            x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


def gradient_image(colors, size, radius):
    """A rounded, horizontally graded swatch. colors: (n, 3) floats 0..1."""
    w, h = size
    colors = np.asarray(colors, dtype=float)
    xs = np.linspace(0, 1, w)
    pos = np.linspace(0, 1, len(colors))
    row = np.stack([np.interp(xs, pos, colors[:, i]) for i in range(3)], axis=-1)
    pixels = (np.repeat(row[None, :, :], h, axis=0) * 255).astype(np.uint8)
    img = Image.fromarray(pixels, "RGB").convert("RGBA")
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    img.putalpha(mask)
    return img


def blend(fg, bg, amount):
    """fg over bg at `amount` (0..1), both '#rrggbb'."""
    return to_hex(rgb01(bg) + (rgb01(fg) - rgb01(bg)) * amount)


def app_icon(size=256):
    """Rounded accent square with four equalizer bars, topped green, yellow
    and red like Typing mode's three guesses."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 4, fill=ACCENT)
    bar_w, gap = size * 0.12, size * 0.07
    x = (size - (4 * bar_w + 3 * gap)) / 2
    caps = ("#4ade80", "#fbbf24", "#f87171", "white")
    for h, cap in zip((0.35, 0.62, 0.48, 0.25), caps):
        top = size * (0.78 - h * 0.9)
        d.rounded_rectangle((x, top, x + bar_w, size * 0.78), radius=bar_w / 2, fill="white")
        d.ellipse((x, top, x + bar_w, top + bar_w), fill=cap)
        x += bar_w + gap
    return img


# ---------------------------------------------------------------- device preview

class DevicePreview(tk.Canvas):
    """Draws a device's LEDs - keycaps for key grids, dots for strips - glowing
    in the current colors."""

    def __init__(self, master, scale=1.0, **kw):
        super().__init__(master, bg=STAGE, highlightthickness=0, **kw)
        self.scale = scale
        self.layout = None
        self.title = ""
        self.items = []
        self.origin, self.unit = (0, 0), 1
        self.colors = np.zeros((0, 3))
        self._base = rgb01(KEY_OFF)
        self._stage = rgb01(STAGE)
        self.font = tkfont.Font(family=FONT, size=-round(12 * scale))
        self.bind("<Configure>", lambda e: self._layout())

    def set_layout(self, lay, title=""):
        self.layout, self.title = lay, title
        self.colors = np.zeros((lay.n if lay else 0, 3))
        self._layout()

    def _layout(self):
        self.delete("all")
        self.items = []
        w, h = self.winfo_width(), self.winfo_height()
        lay = self.layout
        if lay is None:
            self.create_text(w / 2, h / 2, text="No device selected", fill=FAINT, font=self.font)
            return
        self.create_text(14 * self.scale, 12 * self.scale, text=self.title, anchor="nw",
                         fill=FAINT, font=self.font)
        margin = 0.06 * min(w, h) + 22 * self.scale
        s = min((w - 2 * margin) / lay.width, (h - 2 * margin) / lay.depth, 60 * self.scale)
        ox, oy = (w - lay.width * s) / 2, (h - lay.depth * s) / 2
        self.origin, self.unit = (ox, oy), s  # layout units -> pixels, for hit testing
        gap, radius, glow = 0.07 * s, 0.2 * s, 0.13 * s
        for x, y, kw, kh in lay.rects:
            x0, y0 = ox + x * s + gap, oy + y * s + gap
            x1, y1 = ox + (x + kw) * s - gap, oy + (y + kh) * s - gap
            if lay.round:
                halo = self.create_oval(x0 - glow, y0 - glow, x1 + glow, y1 + glow,
                                        fill=STAGE, outline="")
                key = self.create_oval(x0, y0, x1, y1, fill=KEY_OFF, outline=KEY_OUTLINE)
            else:
                halo = self.create_polygon(
                    rounded_points(x0 - glow, y0 - glow, x1 + glow, y1 + glow, radius + glow),
                    smooth=True, fill=STAGE, outline="")
                key = self.create_polygon(rounded_points(x0, y0, x1, y1, radius), smooth=True,
                                          fill=KEY_OFF, outline=KEY_OUTLINE, width=1)
            self.items.append((halo, key))
        self.show(self.colors)

    def show(self, colors):
        if colors is None or len(colors) != len(self.items):
            return  # frame for a different layout (the selection just changed)
        self.colors = colors
        for (halo, key), c in zip(self.items, colors):
            if float(c.max()) < 0.02:
                self.itemconfigure(halo, fill=STAGE)
                self.itemconfigure(key, fill=KEY_OFF, outline=KEY_OUTLINE)
                continue
            fill = np.maximum(self._base, c)
            self.itemconfigure(halo, fill=to_hex(self._stage + (c - self._stage) * 0.28))
            self.itemconfigure(key, fill=to_hex(fill), outline=to_hex(fill + (1 - fill) * 0.35))
