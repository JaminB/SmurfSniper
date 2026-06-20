"""On-demand cross-network intel for the current opponent(s) (Ctrl+F2).

Gathers an opponent's footprint on other esports / game networks when their handle
is distinctive enough to be worth it, and renders it in a dedicated overlay. Built
to run its network fetches off the Qt thread (in the hotkey thread) and only touch
Qt widgets in ``render_overlay``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QTimer

from smurfsniper.api import cross_network
from smurfsniper.logger import logger
from smurfsniper.models.config import OverlayPreferences
from smurfsniper.models.player import PlayerStats
from smurfsniper.ui.overlays import Overlay


@dataclass
class ExternalIntel:
    name: str
    region: str
    aligulac: Optional[dict] = None
    liquipedia: Optional[Tuple[str, str]] = None
    twitch_live: Optional[dict] = None
    handle_urls: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def gather(cls, stats: PlayerStats) -> Optional["ExternalIntel"]:
        """Run the distinctiveness gate, then fetch every source.

        Returns ``None`` when the name is not distinctive enough (caller can
        report "skipped"). Network calls run here, off the Qt thread.
        """
        char = stats.members.character
        name = char.name

        if not cross_network.is_distinctive_name(name):
            logger.info(f"Ctrl+F2: {name!r} not distinctive — skipping lookup.")
            return None

        logger.info(f"Ctrl+F2: gathering cross-network intel for {name!r}.")
        return cls(
            name=name,
            region=char.region,
            aligulac=cross_network.aligulac_player(name),
            liquipedia=cross_network.liquipedia_page(name),
            twitch_live=cross_network.twitch_live(char.id),
            handle_urls=cross_network.candidate_handle_urls(name),
        )

    def to_block(self) -> str:
        """Render this opponent's intel as a single overlay text block."""
        base = self.name.split("#")[0].strip()
        lines = [f"🔎 {base}  ({self.region})"]

        if self.aligulac:
            bio = " · ".join(
                p for p in (
                    self.aligulac.get("country"),
                    self.aligulac.get("name"),
                    self.aligulac.get("race"),
                ) if p
            )
            url = self.aligulac.get("profile_url")
            lines.append(f"Aligulac: {bio or '?'}" + (f"\n  {url}" if url else ""))

        if self.liquipedia:
            title, url = self.liquipedia
            lines.append(f"Liquipedia: {title}\n  {url}")

        if self.twitch_live:
            title = self.twitch_live.get("title") or "live now"
            url = self.twitch_live.get("url")
            lines.append(f"🔴 Twitch LIVE: {title}" + (f"\n  {url}" if url else ""))

        if self.handle_urls:
            guesses = "  ".join(self.handle_urls.values())
            lines.append(f"guesses: {guesses}")

        if len(lines) == 1:
            lines.append("no cross-network footprint found")

        return "\n".join(lines)


def render_overlay(
    intels: List[ExternalIntel], prefs: OverlayPreferences
) -> None:
    """Build and show the external-intel overlay. Must run on the Qt thread."""
    if not intels:
        return

    ov = Overlay(prefs.seconds_visible)
    ov.position = prefs.position

    for intel in intels:
        ov.add_row([intel.to_block()], style=Overlay.PLAYER_STYLE, spacing=12)

    delay = prefs.seconds_delay_before_show
    if delay <= 0:
        ov.show()
        return
    QTimer.singleShot(int(delay * 1000), ov.show)
