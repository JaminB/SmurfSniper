"""Design tokens shared by every window. All pixel values are at scale 1.0.

Overlay code never hard-codes a size or colour: it goes through ``TokenContext``,
which applies the configured opacity and scale (``px``) to these values.
"""

from __future__ import annotations

from dataclasses import dataclass

FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Arial"]
EMOJI_FAMILIES = ["Segoe UI Emoji", "Noto Color Emoji", "Apple Color Emoji"]
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

SMURF_BADGE = {  # level -> (fg, bg rgba, border rgba)
    "suspicious": ((253, 230, 138), (234, 179, 8, 46), (234, 179, 8, 110)),
    "possible": ((254, 215, 170), (249, 115, 22, 51), (249, 115, 22, 120)),
    "likely": ((254, 202, 202), (239, 68, 68, 56), (239, 68, 68, 140)),
}
SMURF_LABEL = {"suspicious": "SUSPICIOUS", "possible": "POSSIBLE SMURF", "likely": "LIKELY SMURF"}
SMURF_SHORT = {"suspicious": "SUSPICIOUS", "possible": "POSSIBLE", "likely": "LIKELY"}
PRO_BADGE = ((165, 243, 252), (34, 211, 238, 46), (34, 211, 238, 120))

CHIP = {
    "fg": (229, 231, 235),
    "bg": (255, 255, 255, 26),
    "border": (255, 255, 255, 46),
    "pad_x": 6,
    "pad_y": 2,
    "font": "mono",
}

SIZE = {
    "card_min_w": 248,
    "card_max_w": 320,
    "toast_w": 288,
    "panel_w": 360,
    "panel_max_h": 520,
    "hint_h": 28,
    "row_h": 18,
    "badge_h": 18,
    "sparkline_chars": 12,
}
PADDING = {  # (vertical, horizontal)
    "card": (10, 12),
    "toast": (10, 12),
    "panel": (12, 14),
    "panel_header": (8, 12),
    "hint": (4, 12),
}
GAP = {"row": 4, "section": 8, "toast_stack": 8, "inline": 6}

ANIM = {  # (ms, QEasingCurve name)
    "fade_in": (160, "OutCubic"),
    "fade_out": (220, "InCubic"),
    "slide_px": 12,
    "slide_in": (180, "OutCubic"),
    "row_reveal": (140, "OutCubic"),
    "card_resize": (140, "OutCubic"),
    "toast_default_ms": 6000,
    "toast_recap_ms": 10000,
    "hint_ms": 6000,
}


def px(value: float, scale: float = 1.0) -> int:
    """Scale a token pixel value."""
    return round(value * scale)


def css(color: tuple[int, ...]) -> str:
    """``(r, g, b[, a])`` -> CSS ``rgba()`` string (alpha 0-255 as in the tokens)."""
    if len(color) == 3:
        return f"rgb({color[0]}, {color[1]}, {color[2]})"
    return f"rgba({color[0]}, {color[1]}, {color[2]}, {color[3] / 255:.3f})"


def alpha(opacity: float) -> int:
    """Surface opacity (0-1) -> 0-255 alpha, clamped."""
    return max(0, min(255, round(opacity * 255)))


@dataclass(frozen=True)
class TokenContext:
    """Live overlay settings applied to the tokens. Immutable; rebuilt on config change."""

    opacity: float = 0.70
    scale: float = 1.0
    screen: int | None = None

    @classmethod
    def from_overlays(cls, ov) -> TokenContext:
        """From an ``OverlayConfig`` (duck-typed: ``opacity``, ``scale``, ``screen``)."""
        return cls(opacity=ov.opacity, scale=ov.scale, screen=ov.screen)

    def px(self, value: float) -> int:
        return px(value, self.scale)

    @property
    def surface_alpha(self) -> int:
        return alpha(self.opacity)

    @property
    def raised_alpha(self) -> int:
        return alpha(min(self.opacity + 0.10, 1.0))

    def font_px(self, role: str) -> int:
        return max(1, self.px(FONT_SIZE[role]))
