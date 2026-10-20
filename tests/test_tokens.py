from __future__ import annotations

from datetime import UTC, datetime, timedelta

from smurfsniper.analyze.history import Record
from smurfsniper.analyze.matches import RecentResult
from smurfsniper.analyze.smurf import LEVELS
from smurfsniper.ui import fmt, theme
from smurfsniper.ui import tokens as t
from smurfsniper.ui.tokens import TokenContext, alpha, px


def test_px_scales_and_rounds():
    assert px(12) == 12
    assert px(12, 1.25) == 15
    assert px(10, 1.5) == 15
    assert TokenContext(scale=0.75).px(24) == 18
    assert TokenContext(scale=1.25).font_px("body") == 15


def test_alpha_from_opacity():
    assert alpha(0.0) == 0 and alpha(1.0) == 255 and alpha(2.0) == 255
    tk = TokenContext(opacity=0.70)
    assert tk.surface_alpha == round(0.70 * 255)
    assert tk.raised_alpha == round(0.80 * 255)
    assert TokenContext(opacity=0.95).raised_alpha == 255


def test_every_race_has_accent_and_glyph():
    for race in ("ZERG", "TERRAN", "PROTOSS", "RANDOM", None):
        assert race in t.RACE_ACCENT
    assert set(t.RACE_GLYPH) == {"ZERG", "TERRAN", "PROTOSS", "RANDOM"}


def test_badge_levels_match_smurf_levels():
    levels = {lvl for _, lvl in LEVELS}
    assert set(t.SMURF_BADGE) == levels
    assert set(t.SMURF_LABEL) == levels
    assert set(t.SMURF_SHORT) == levels


def test_theme_uses_tokens():
    assert t.css(t.SURFACE) == theme.BG
    assert t.css(t.SURFACE_RAISED) == theme.RAISED
    assert t.css(t.INFO) == theme.ACCENT


def test_token_context_from_config():
    from smurfsniper.models.config import Config

    cfg = Config()
    cfg.overlays.opacity = 0.5
    cfg.overlays.scale = 1.25
    tk = TokenContext.from_overlays(cfg.overlays)
    assert (tk.opacity, tk.scale, tk.screen) == (0.5, 1.25, None)


# ------------------------------------------------------------------ fmt
def test_fmt_records_skip_empty_windows():
    recs = {"3d": Record(0, 0), "7d": Record(15, 3), "30d": Record(20, 9), "season": Record(1, 1)}
    assert fmt.records_line(recs) == "7d 15-3 · 30d 20-9"
    assert fmt.records_line({"3d": Record(0, 0)}) is None
    assert fmt.record_text(Record(0, 0)) is None


def test_fmt_never_returns_placeholders():
    assert fmt.h2h_record(0, 0) is None
    assert fmt.h2h_record(3, 1) == "3-1" and fmt.h2h_record(1, 1, 1) == "1-1-1"
    assert fmt.mmr(None) is None and fmt.mmr(0) is None and fmt.mmr(4210) == "4,210 MMR"
    assert fmt.duration(None) is None and fmt.duration(680) == "11:20"
    assert fmt.league_label(None) is None and fmt.league_label(99) is None
    assert fmt.join([None, ""]) is None


def test_fmt_league_and_percent():
    assert fmt.league_label(4, 1) == "Diamond 2"
    assert fmt.league_label(6, 0) == "Grandmaster"
    assert fmt.league_label(6, 0, short=True) == "GM"
    assert fmt.top_percent(91.0) == "top 9%"
    assert fmt.top_percent(99.95) == "top 0.1%"
    assert fmt.top_percent(20.0) is None  # bottom half is noise


def test_fmt_intel_bits():
    assert fmt.aligulac_rating(2.4312, 12) == "Aligulac 3,431 (#12)"
    assert fmt.aligulac_rating(0.0, None) == "Aligulac 1,000"
    assert fmt.aligulac_rating(None, 1) is None
    assert fmt.country("fi", emoji=False) == "FI"
    assert fmt.country("FI", emoji=True) == "\U0001f1eb\U0001f1ee"
    assert fmt.country("Finland") is None
    assert fmt.link_label("REPLAY_STATS") == "Replay Stats"
    assert fmt.earnings(0) is None


def test_fmt_vs_race_needs_enough_games():
    now = datetime(2026, 10, 19, tzinfo=UTC)

    def r(won: bool, race: str) -> RecentResult:
        return RecentResult(now - timedelta(hours=1), won, "Map", 600, "ZERG", race)

    recent = [r(True, "ZERG"), r(True, "ZERG"), r(False, "ZERG"), r(True, "TERRAN")]
    assert fmt.vs_race(recent, "ZERG") == "vs Z 67%"
    assert fmt.vs_race(recent, "TERRAN") is None
    assert fmt.vs_race(recent, None) is None
