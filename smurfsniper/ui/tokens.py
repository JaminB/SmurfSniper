"""Design tokens shared by every window. All pixel values are at scale 1.0."""

from __future__ import annotations

FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Arial"]
FONT_FAMILY_CSS = '"Segoe UI Variable Text", "Segoe UI", Inter, sans-serif'
FONT_MONO = ["Cascadia Mono", "Consolas"]
FONT_MONO_CSS = '"Cascadia Mono", Consolas, monospace'
FONT_SIZE = {"title": 15, "body": 12, "caption": 11, "micro": 10, "mono": 11, "badge": 10}
FONT_WEIGHT = {"title": 600, "body": 400, "caption": 400, "badge": 700, "mono": 500}

SPACE = {"xxs": 2, "xs": 4, "sm": 6, "md": 8, "lg": 12, "xl": 16, "xxl": 20}
RADIUS = {"card": 12, "panel": 14, "toast": 10, "chip": 6, "badge": 999, "hint": 999}
BORDER_WIDTH = 1
ACCENT_BAR_WIDTH = 3
SCREEN_MARGIN = 24
SHADOW = {"blur": 24, "dx": 0, "dy": 4, "color": (0, 0, 0, 115)}

SURFACE = (14, 16, 22)
SURFACE_RAISED = (28, 31, 40)
BORDER = (255, 255, 255, 20)
DIVIDER = (255, 255, 255, 13)

TEXT_PRIMARY = (242, 244, 248)
TEXT_SECONDARY = (169, 176, 190)
TEXT_MUTED = (107, 114, 128)
POSITIVE = (61, 220, 132)
NEGATIVE = (255, 92, 92)
INFO = (96, 165, 250)
WARNING = (245, 184, 61)

RACE_ACCENT = {
    "ZERG": (168, 85, 247),
    "TERRAN": (59, 130, 246),
    "PROTOSS": (245, 184, 61),
    "RANDOM": (156, 163, 175),
    None: (156, 163, 175),
}
RACE_GLYPH = {"ZERG": "Z", "TERRAN": "T", "PROTOSS": "P", "RANDOM": "R"}

CHIP = {
    "fg": (229, 231, 235),
    "bg": (255, 255, 255, 26),
    "border": (255, 255, 255, 46),
    "pad_x": 6,
    "pad_y": 2,
    "font": "mono",
}


def px(value: float, scale: float = 1.0) -> int:
    """Scale a token pixel value."""
    return round(value * scale)


def css(color: tuple[int, ...]) -> str:
    """``(r, g, b[, a])`` -> CSS ``rgba()`` string (alpha 0-255 as in the tokens)."""
    if len(color) == 3:
        return f"rgb({color[0]}, {color[1]}, {color[2]})"
    return f"rgba({color[0]}, {color[1]}, {color[2]}, {color[3] / 255:.3f})"
