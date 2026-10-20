"""Fake opponent data for the Settings preview, ``scripts/render_preview.py`` and tests.

Everything is built from the real typed models, so previews exercise the same code
paths as live games. Names are invented.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from smurfsniper.analyze.h2h import H2HInfo
from smurfsniper.analyze.history import Record, Trend
from smurfsniper.analyze.matches import RecentResult
from smurfsniper.analyze.smurf import SmurfAssessment, SmurfReason
from smurfsniper.analyze.team import TeamInfo
from smurfsniper.api.aligulac.models import AligulacPlayer
from smurfsniper.api.liquipedia.models import PageSummary
from smurfsniper.api.sc2pulse.models import (
    Character,
    Clan,
    LadderDistinctCharacter,
    LadderTeam,
    Member,
    ProPlayer,
    ProPlayerEntry,
    ProTeam,
    SeasonStats,
    SocialLink,
)
from smurfsniper.core.profile import (
    GameSeed,
    Identity,
    IntelInfo,
    LookupUpdate,
    OpponentProfile,
    RatingInfo,
    SmurfInfo,
    Stage,
    TendenciesInfo,
)

NOW = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)
_IDS = iter(range(1000, 100000))


def _identity(
    name: str,
    race: str,
    *,
    region: str = "EU",
    clan: str | None = None,
    pro: ProPlayerEntry | None = None,
    rating: int | None = None,
    rating_max: int | None = None,
    league_max: int | None = None,
) -> Identity:
    i = next(_IDS)
    ch = Character(
        id=i, account_id=i, region=region, realm=1, battlenet_id=i, name=f"{name}#{i % 997}"
    )
    member = Member(
        character=ch,
        clan=Clan(id=i, tag=clan) if clan else None,
        pro_player=pro,
        race_games={race: 120},
    )
    cand = LadderDistinctCharacter(
        members=member,
        rating_max=rating_max,
        league_max=league_max,
        current_stats=SeasonStats(rating=rating, games_played=60),
    )
    return Identity(character=ch, clan=member.clan, pro=pro, candidate=cand, confidence=0.95)


def _rating(mmr: int, league: int, tier: int | None, pct: float, w: int, lo: int, peak=None):
    return RatingInfo(
        mmr=mmr,
        league=league,
        tier=tier,
        region_percentile=pct,
        season_wins=w,
        season_losses=lo,
        peak_mmr=peak,
        peak_league=None,
        mmr_to_next_tier=None,
        team=None,
    )


def _recent(results: str, opp_races: str, maps: list[str], secs: int) -> list[RecentResult]:
    races = {"Z": "ZERG", "T": "TERRAN", "P": "PROTOSS"}
    out = []
    for i, ch in enumerate(results):
        out.append(
            RecentResult(
                ts=NOW - timedelta(hours=3 * i + 1),
                won=ch == "W",
                map=maps[i % len(maps)],
                duration_s=secs + 37 * (i % 5) - 60,
                race="ZERG",
                opponent_race=races[opp_races[i % len(opp_races)]],
            )
        )
    return out


# ------------------------------------------------------------------- profiles
SERRAL_PRO = ProPlayerEntry(
    pro_player=ProPlayer(
        id=1, aligulac_id=485, nickname="Serral", name="Joona Sotala", country="FI",
        earnings=1_164_000,
    ),
    pro_team=ProTeam(id=1, name="BASILISK", short_name="BSLSK"),
    links=[
        SocialLink(type="LIQUIPEDIA", url="https://liquipedia.net/starcraft2/Serral"),
        SocialLink(type="TWITCH", url="https://www.twitch.tv/serral"),
    ],
)  # fmt: skip


def pro_profile() -> OpponentProfile:
    """1v1 vs a pro: identity + rating (frame t1)."""
    ident = _identity(
        "Serral", "ZERG", clan="BSLSK", pro=SERRAL_PRO, rating=7065, rating_max=7557,
        league_max=6,
    )  # fmt: skip
    return OpponentProfile(
        seed=GameSeed("Serral", "ZERG"),
        identity=ident,
        rating=_rating(7065, 6, None, 99.95, 98, 21),
    )


def smurf_profile() -> OpponentProfile:
    """1v1 vs a likely smurf with every stage (frame t2)."""
    ident = _identity("xXbarcodeXx", "ZERG", rating=4410, rating_max=4410, league_max=4)
    outcomes = SmurfAssessment(
        82,
        "likely",
        (
            SmurfReason("wr3d", "3d winrate 9/10", 35),
            SmurfReason("age", "new account (9d)", 30),
            SmurfReason("climb", "climb +31/day", 20),
        ),
    )
    return OpponentProfile(
        seed=GameSeed("xXbarcodeXx", "ZERG"),
        identity=ident,
        rating=_rating(4410, 4, 0, 91.2, 24, 4),
        smurf=SmurfInfo(
            assessment=outcomes,
            trend=Trend(31.0, "▲"),
            sparkline="▁▂▂▃▃▄▅▆▆▇█",
            records={"3d": Record(9, 1), "7d": Record(15, 3)},
        ),
        h2h=H2HInfo(1, 0, 1, 0, NOW - timedelta(days=3), NOW - timedelta(days=3)),
        tendencies=TendenciesInfo(
            recent=_recent("WWLWWWLLWW", "ZZTZP", ["Alcyone LE", "Rainfall LE", "Pylon LE"], 460),
            maps={
                "Alcyone LE": Record(4, 1),
                "Rainfall LE": Record(3, 0),
                "Pylon LE": Record(2, 1),
            },
            avg_duration_s=460,
        ),
    )


def seed_profile() -> OpponentProfile:
    """Frame t0: only the GAME stage."""
    return OpponentProfile(seed=GameSeed("Serral", "ZERG"))


def duo_profiles() -> list[OpponentProfile]:
    a = OpponentProfile(
        seed=GameSeed("PlayerA", "TERRAN"),
        identity=_identity("PlayerA", "TERRAN", rating=5120),
        rating=_rating(5120, 5, 1, 96.0, 40, 22),
    )
    b = OpponentProfile(
        seed=GameSeed("PlayerB", "PROTOSS"),
        identity=_identity("PlayerB", "PROTOSS", rating=3980),
        rating=_rating(3980, 4, 2, 84.0, 18, 6),
        smurf=SmurfInfo(
            SmurfAssessment(51, "possible", (SmurfReason("climb", "climb +12/day", 10),)),
            Trend(12.0, "▲"),
            "▂▃▄▅▆▇",
            {"7d": Record(11, 3)},
        ),
    )
    return [a, b]


def duo_team() -> TeamInfo:
    team = LadderTeam(
        id=77, rating=4410, wins=12, losses=4, season=63, region="EU", league_type=5, tier_type=0
    )
    return TeamInfo(team=team, members_races=["TERRAN", "PROTOSS"])


def quad_profiles() -> list[OpponentProfile]:
    rows = [
        ("Alpha", "TERRAN", 3120, None),
        ("Bravo", "ZERG", 4950, (74, "likely", "3d winrate 9/10")),
        ("Charlie", "PROTOSS", 2870, None),
        ("Delta", "ZERG", 3300, None),
    ]
    out = []
    for name, race, mmr, smurf in rows:
        prof = OpponentProfile(
            seed=GameSeed(name, race),
            identity=_identity(name, race, rating=mmr),
            rating=_rating(mmr, 3, 1, 60.0, 10, 10),
        )
        if smurf is not None:
            score, level, reason = smurf
            prof.smurf = SmurfInfo(
                SmurfAssessment(score, level, (SmurfReason("wr3d", reason, 35),)), None, None, {}
            )
        out.append(prof)
    return out


def intel_profile() -> OpponentProfile:
    prof = pro_profile()
    smurfy = smurf_profile()
    prof.tendencies = smurfy.tendencies
    prof.intel = IntelInfo(
        pro=SERRAL_PRO,
        aligulac=AligulacPlayer(
            id=485,
            tag="Serral",
            country="FI",
            race="Z",
            current_rating={"rating": 2.4312, "position": 1},
            team="BASILISK",
        ),
        liquipedia=PageSummary(
            title="Serral",
            pageid=1,
            extract=(
                "Joona Sotala, better known as Serral, is a Finnish Zerg player who "
                "currently plays for BASILISK. Widely considered one of the best players "
                "in the world, he became the first non-Korean to win a WCS Global Finals "
                "in 2018 and has since won multiple premier titles."
            ),
            full_url="https://liquipedia.net/starcraft2/Serral",
        ),
        links=list(SERRAL_PRO.links),
    )
    return prof


def updates_for(game_id: int, slot: int, prof: OpponentProfile) -> list[LookupUpdate]:
    """The pipeline updates that would have produced ``prof`` (in stage order)."""
    out = [LookupUpdate(game_id, slot, Stage.GAME, prof.seed)]
    for stage, data in (
        (Stage.IDENTITY, prof.identity),
        (Stage.RATING, prof.rating),
        (Stage.SMURF, prof.smurf),
        (Stage.H2H, prof.h2h),
        (Stage.TENDENCIES, prof.tendencies),
        (Stage.INTEL, prof.intel),
    ):
        if data is not None:
            out.append(LookupUpdate(game_id, slot, stage, data))
    return out
