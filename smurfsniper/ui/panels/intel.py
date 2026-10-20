"""Scouting-intel panel body: pro info, tendencies and link types per opponent.

Every section and row is omitted when it has no data; ``build_intel_body`` returns
None when nothing at all is known.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import QWidget

from smurfsniper.core.profile import IntelInfo, OpponentProfile, TendenciesInfo
from smurfsniper.ui import fmt
from smurfsniper.ui import tokens as t
from smurfsniper.ui.overlay.card import dotted
from smurfsniper.ui.overlay.widgets import (
    Badge,
    Part,
    RaceDot,
    Row,
    Section,
    Text,
    elide_lines,
    key_label,
    key_row,
)
from smurfsniper.ui.tokens import TokenContext

LINKS_HINT = "(tray → Last opponent links)"
EXTRACT_LINES = 4


def links_of(profiles: Sequence[OpponentProfile]) -> list[tuple[str, str]]:
    """``[(label, url)]`` for the tray's "Last opponent links" menu."""
    out: list[tuple[str, str]] = []
    for prof in profiles:
        intel = prof.intel
        if intel is None:
            continue
        name = prof.identity.character.base_name if prof.identity else prof.seed.name
        seen: set[str] = set()
        for link in intel.links:
            if link.url and link.url not in seen:
                seen.add(link.url)
                out.append((f"{name}: {fmt.link_label(link.type)}", link.url))
        if intel.aligulac is not None and intel.aligulac.profile_url not in seen:
            out.append((f"{name}: Aligulac", intel.aligulac.profile_url))
        lp = intel.liquipedia
        if lp is not None and lp.full_url and lp.full_url not in seen:
            out.append((f"{name}: Liquipedia", lp.full_url))
    return out


def _pro_rows(intel: IntelInfo, tk: TokenContext, width: int) -> list[QWidget]:
    rows: list[QWidget | None] = []
    pro = intel.pro
    if pro is not None:
        pp = pro.pro_player
        team = pro.pro_team.short_name or pro.pro_team.name if pro.pro_team else None
        rows.append(
            Row.create(
                tk,
                dotted(
                    [
                        Part(pp.nickname, "body", t.TEXT_PRIMARY, 600),
                        Part(team, "caption", t.TEXT_SECONDARY),
                        Part(fmt.country(pp.country), "caption", t.TEXT_MUTED),
                    ]
                ),
                lead=Badge.pro(tk),
            )
        )
    ali = intel.aligulac
    cr = ali.current_rating if ali is not None else None
    rows.append(
        Row.create(
            tk,
            dotted(
                [
                    Part(
                        fmt.aligulac_rating(cr.rating, cr.position) if cr else None,
                        "caption",
                        t.TEXT_SECONDARY,
                    ),
                    Part(
                        ali.team if ali is not None and pro is None else None,
                        "caption",
                        t.TEXT_SECONDARY,
                    ),
                    Part(
                        fmt.earnings(pro.pro_player.earnings) if pro else None,
                        "caption",
                        t.TEXT_SECONDARY,
                    ),
                ]
            ),
        )
    )
    lp = intel.liquipedia
    if lp is not None and lp.extract and lp.extract.strip():
        label = Text("", tk, role="caption", color=t.TEXT_SECONDARY, wrap=True)
        label.setText(elide_lines(lp.extract.strip(), label.font(), width, EXTRACT_LINES))
        rows.append(label)
    return [r for r in rows if r is not None]


def _tendency_rows(tend: TendenciesInfo, tk: TokenContext) -> list[QWidget]:
    rows: list[QWidget | None] = []
    recent = fmt.form(tend.recent)
    if recent:
        pos, neg = t.css(t.POSITIVE), t.css(t.NEGATIVE)
        letters = "&nbsp;".join(
            f'<span style="color:{pos if w else neg}">{"W" if w else "L"}</span>' for w in recent
        )
        avg = fmt.duration(tend.avg_duration_s)
        row = Row(tk)
        row.lay.addWidget(key_label(tk, "FORM"))
        row.lay.addWidget(Text(letters, tk, role="caption", weight=600, rich=True))
        if avg:
            row.lay.addWidget(Text("·", tk, role="caption", color=t.TEXT_MUTED))
            row.lay.addWidget(Text(f"avg {avg}", tk, role="caption", color=t.TEXT_SECONDARY))
        row.lay.addStretch(1)
        rows.append(row)
    elif tend.avg_duration_s:
        rows.append(
            key_row(
                tk, "LENGTH", [Part(fmt.duration(tend.avg_duration_s), "caption", t.TEXT_SECONDARY)]
            )
        )
    maps = fmt.top_maps(tend.maps)
    rows.append(key_row(tk, "MAPS", [Part(maps, "caption", t.TEXT_SECONDARY, elide=True)]))
    return [r for r in rows if r is not None]


def _links_row(intel: IntelInfo, tk: TokenContext) -> QWidget | None:
    kinds: list[str] = []
    for link in intel.links:
        label = fmt.link_label(link.type)
        if label not in kinds:
            kinds.append(label)
    if intel.aligulac is not None and "Aligulac" not in kinds:
        kinds.append("Aligulac")
    if not kinds:
        return None
    return key_row(
        tk,
        "LINKS",
        [
            Part(" · ".join(kinds[:4]), "caption", t.TEXT_SECONDARY),
            Part(LINKS_HINT, "micro", t.TEXT_MUTED),
        ],
    )


def opponent_section(prof: OpponentProfile, tk: TokenContext, *, with_name: bool) -> Section | None:
    width = tk.px(t.SIZE["panel_w"] - 2 * t.PADDING["panel"][1] - t.ACCENT_BAR_WIDTH)
    sec = Section(tk)
    rows: list[QWidget] = []
    if prof.intel is not None:
        rows.extend(_pro_rows(prof.intel, tk, width))
    if prof.tendencies is not None:
        rows.extend(_tendency_rows(prof.tendencies, tk))
    if prof.intel is not None:
        link = _links_row(prof.intel, tk)
        if link is not None:
            rows.append(link)
    if not rows:
        sec.deleteLater()
        return None
    if with_name:
        name = prof.identity.character.base_name if prof.identity else prof.seed.name
        sec.add(
            Row.create(
                tk,
                [Part(name, "body", t.TEXT_PRIMARY, 600, elide=True)],
                lead=RaceDot(prof.seed.race, tk, glyph=False),
            )
        )
    for r in rows:
        sec.add(r)
    return sec


def build_intel_body(profiles: Sequence[OpponentProfile], tk: TokenContext) -> list[QWidget] | None:
    many = len(profiles) > 1
    sections = [s for p in profiles if (s := opponent_section(p, tk, with_name=many)) is not None]
    return sections or None
