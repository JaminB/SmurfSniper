"""Small token-driven building blocks for overlay content.

``Row.create`` returns None when every text part is empty, so callers simply skip
it: this is how the HUD never renders an empty or placeholder row.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPalette
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from smurfsniper.analyze.history import BARS
from smurfsniper.ui import tokens as t
from smurfsniper.ui.overlay.base import animations_enabled, easing, qcolor
from smurfsniper.ui.tokens import TokenContext

RGB = tuple[int, ...]


def make_font(tokens: TokenContext, role: str, *, weight: int | None = None) -> QFont:
    f = QFont()
    families = t.FONT_MONO if role == "mono" else t.FONT_FAMILIES
    f.setFamilies([*families, *t.EMOJI_FAMILIES])
    f.setPixelSize(tokens.font_px(role))
    f.setWeight(QFont.Weight(weight or t.FONT_WEIGHT.get(role, 400)))
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


# ----------------------------------------------------------------------- text
class Text(QLabel):
    """A transparent label with a token font and colour; optionally elides."""

    def __init__(
        self,
        text: str,
        tokens: TokenContext,
        *,
        role: str = "body",
        color: RGB = t.TEXT_PRIMARY,
        weight: int | None = None,
        elide: bool = False,
        wrap: bool = False,
        max_lines: int | None = None,
        rich: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.tokens = tokens
        self.role = role
        self.elide = elide
        self.max_lines = max_lines
        self.setFont(make_font(tokens, role, weight=weight))
        self.setTextFormat(Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText)
        self.set_color(color)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if wrap:
            self.setWordWrap(True)
        if max_lines:
            fm = QFontMetrics(self.font())
            self.setMaximumHeight(fm.lineSpacing() * max_lines + 1)
        if elide:
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setText(text)

    def set_color(self, color: RGB) -> None:
        self.color = qcolor(color)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.WindowText, self.color)
        self.setPalette(pal)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        if self.elide:
            fm = QFontMetrics(self.font())
            return QSize(fm.horizontalAdvance(self.text()) + 2, fm.height())
        return hint

    def minimumSizeHint(self) -> QSize:
        if self.elide:
            fm = QFontMetrics(self.font())
            return QSize(
                min(fm.horizontalAdvance(self.text()), fm.horizontalAdvance("M…") * 2), fm.height()
            )
        return super().minimumSizeHint()

    def paintEvent(self, e) -> None:
        if not self.elide:
            super().paintEvent(e)
            return
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.color)
        fm = QFontMetrics(self.font())
        shown = fm.elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width())
        p.drawText(
            self.rect(), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), shown
        )
        p.end()


def elide_lines(text: str, font: QFont, width: int, max_lines: int) -> str:
    """Word-wrap ``text`` to ``width`` and keep at most ``max_lines``, ending in ``…``."""
    fm = QFontMetrics(font)
    lines: list[str] = []
    words = text.split()
    cur = ""
    i = 0
    while i < len(words):
        trial = f"{cur} {words[i]}".strip()
        if fm.horizontalAdvance(trial) <= width or not cur:
            cur = trial
            i += 1
            continue
        lines.append(cur)
        cur = ""
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if i < len(words) and lines:
        lines[-1] = fm.elidedText(
            lines[-1] + " " + " ".join(words[i:]), Qt.TextElideMode.ElideRight, width
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------- pills
class Pill(QWidget):
    """Rounded label with fill + border (base of ``Badge`` and ``Chip``)."""

    def __init__(
        self,
        text: str,
        tokens: TokenContext,
        *,
        fg: RGB,
        bg: RGB,
        border: RGB,
        role: str = "badge",
        radius: str = "badge",
        pad: tuple[int, int] = (2, 6),
        height: int | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.tokens = tokens
        self._text = text
        self.fg, self.bg, self.border = qcolor(fg), qcolor(bg), qcolor(border)
        self.radius_key = radius
        self.pad = (tokens.px(pad[0]), tokens.px(pad[1]))
        self.setFont(make_font(tokens, role))
        self._height = tokens.px(height) if height else None
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        h = self._height or fm.height() + 2 * self.pad[0]
        return QSize(fm.horizontalAdvance(self._text) + 2 * self.pad[1] + 2, h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        r = min(self.tokens.px(t.RADIUS[self.radius_key]), rect.height() / 2)
        path = QPainterPath()
        path.addRoundedRect(rect, r, r)
        p.fillPath(path, self.bg)
        p.setPen(self.border)
        p.drawPath(path)
        p.setPen(self.fg)
        p.setFont(self.font())
        p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self._text)
        p.end()


class Badge(Pill):
    """Severity / PRO badge: bold caps on a tinted pill."""

    def __init__(self, text: str, colors: tuple[RGB, RGB, RGB], tokens: TokenContext, **kw):
        fg, bg, border = colors
        super().__init__(
            text, tokens, fg=fg, bg=bg, border=border, role="badge", height=t.SIZE["badge_h"], **kw
        )

    @classmethod
    def smurf(cls, level: str, score: int, tokens: TokenContext, *, short: bool = False) -> Badge:
        label = (t.SMURF_SHORT if short else t.SMURF_LABEL)[level]
        return cls(f"{label} {score}", t.SMURF_BADGE[level], tokens)

    @classmethod
    def pro(cls, tokens: TokenContext) -> Badge:
        return cls("PRO", t.PRO_BADGE, tokens)


class Chip(Pill):
    """Keyboard-shortcut chip (mono font), e.g. ``Ctrl+Shift+2 ✕``."""

    def __init__(self, text: str, tokens: TokenContext, **kw):
        c = t.CHIP
        super().__init__(
            text,
            tokens,
            fg=c["fg"],
            bg=c["bg"],
            border=c["border"],
            role=c["font"],
            radius="chip",
            pad=(c["pad_y"], c["pad_x"]),
            **kw,
        )


class RaceDot(QWidget):
    """Race marker: a tinted circle with the race initial, or a plain dot."""

    def __init__(self, race: str | None, tokens: TokenContext, *, glyph: bool = True, parent=None):
        super().__init__(parent)
        self.race = race
        self.tokens = tokens
        self.glyph = glyph and race in t.RACE_GLYPH
        self.color = qcolor(t.RACE_ACCENT.get(race, t.RACE_ACCENT[None]))
        self.setFont(make_font(tokens, "badge"))
        d = tokens.px(18 if self.glyph else 8)
        self.setFixedSize(d, d)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def text(self) -> str:
        return t.RACE_GLYPH.get(self.race or "", "") if self.glyph else ""

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.glyph:
            fill = QColor(self.color)
            fill.setAlpha(46)
            line = QColor(self.color)
            line.setAlpha(140)
            p.setBrush(fill)
            p.setPen(line)
            p.drawEllipse(rect)
            p.setPen(self.color)
            p.setFont(self.font())
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self.text())
        else:
            p.setBrush(self.color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(rect)
        p.end()


class Sparkline(QWidget):
    """Mini bar chart from a ``▁▂▃▄▅▆▇█`` string (the analysis output)."""

    def __init__(
        self, bars: str, tokens: TokenContext, *, color: RGB = t.TEXT_SECONDARY, parent=None
    ):
        super().__init__(parent)
        n = t.SIZE["sparkline_chars"]
        self.levels = [BARS.index(c) for c in bars if c in BARS][-n:]
        self.tokens = tokens
        self.color = qcolor(color)
        self._bar = tokens.px(3)
        self._gap = max(1, tokens.px(1))
        self.setFixedSize(self.sizeHint())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def sizeHint(self) -> QSize:
        n = max(1, len(self.levels))
        return QSize(n * self._bar + (n - 1) * self._gap, self.tokens.px(12))

    def paintEvent(self, _e) -> None:
        if not self.levels:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        top = len(BARS) - 1
        for i, lvl in enumerate(self.levels):
            bh = max(2.0, h * (lvl + 1) / (top + 1))
            c = QColor(self.color)
            c.setAlphaF(0.45 + 0.55 * (i + 1) / len(self.levels))
            x = i * (self._bar + self._gap)
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, h - bh, self._bar, bh), 1, 1)
            p.fillPath(path, c)
        p.end()


class Divider(QWidget):
    def __init__(self, tokens: TokenContext, parent=None):
        super().__init__(parent)
        self.setFixedHeight(max(1, t.BORDER_WIDTH))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._color = qcolor(t.DIVIDER)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), self._color)
        p.end()


class Skeleton(QWidget):
    """Pulsing loading row. The only placeholder allowed, and only while a stage runs."""

    def __init__(self, label: str, tokens: TokenContext, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(tokens.px(t.GAP["inline"]))
        self.label = Text(label, tokens, role="caption", color=t.TEXT_SECONDARY)
        lay.addWidget(self.label)
        lay.addStretch(1)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._pulse = QPropertyAnimation(self._effect, b"opacity", self)
        self._pulse.setDuration(1200)
        self._pulse.setKeyValueAt(0.0, 0.35)
        self._pulse.setKeyValueAt(0.5, 1.0)
        self._pulse.setKeyValueAt(1.0, 0.35)
        self._pulse.setLoopCount(-1)
        if animations_enabled():
            self._pulse.start()


# ----------------------------------------------------------------------- rows
@dataclass(frozen=True)
class Part:
    """One text run in a row."""

    text: str | None
    role: str = "body"
    color: RGB = t.TEXT_PRIMARY
    weight: int | None = None
    elide: bool = False


class Row(QWidget):
    """HBox: optional leading widget, text parts, stretch, trailing widgets."""

    def __init__(self, tokens: TokenContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.tokens = tokens
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(tokens.px(t.GAP["inline"]))
        self.setMinimumHeight(tokens.px(t.SIZE["row_h"]))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    @classmethod
    def create(
        cls,
        tokens: TokenContext,
        parts: Sequence[Part | None],
        *,
        lead: QWidget | None = None,
        trailing: Sequence[QWidget | None] = (),
        stretch: bool = True,
    ) -> Row | None:
        kept = [p for p in parts if p is not None and p.text]
        if not kept:
            for w in (lead, *trailing):
                if w is not None:
                    w.deleteLater()
            return None
        row = cls(tokens)
        if lead is not None:
            row.lay.addWidget(lead, 0, Qt.AlignmentFlag.AlignVCenter)
        for part in kept:
            label = Text(
                part.text or "",
                tokens,
                role=part.role,
                color=part.color,
                weight=part.weight,
                elide=part.elide,
            )
            row.lay.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        if stretch:
            row.lay.addStretch(1)
        for w in trailing:
            if w is not None:
                row.lay.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def texts(self) -> list[str]:
        return [w.text() for w in self.findChildren(QLabel)]


def reveal_row(widget: QWidget) -> None:
    """Fade a newly added row in (``row_reveal``); the effect is removed afterwards."""
    if not animations_enabled():
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    dur, curve = t.ANIM["row_reveal"]
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(dur)
    anim.setEasingCurve(easing(curve))
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


class Section(QWidget):
    """Vertical group of rows with an optional caps key column (panel sections)."""

    def __init__(self, tokens: TokenContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.tokens = tokens
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(tokens.px(t.GAP["row"]))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def add(self, w: QWidget | None) -> bool:
        if w is None:
            return False
        self.lay.addWidget(w)
        return True

    def is_empty(self) -> bool:
        return self.lay.count() == 0


def key_label(tokens: TokenContext, key: str, *, width: int = 44) -> Text:
    """Muted caps key column used by panel rows (``FORM``, ``MAPS``...)."""
    k = Text(key, tokens, role="micro", color=t.TEXT_MUTED, weight=600)
    k.setFixedWidth(tokens.px(width))
    return k


def key_row(tokens: TokenContext, key: str, parts: Sequence[Part | None]) -> Row | None:
    """``MAPS   Alcyone 4-1`` style row; None when every value is empty."""
    if not any(p is not None and p.text for p in parts):
        return None
    return Row.create(tokens, parts, lead=key_label(tokens, key))
