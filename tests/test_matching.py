from __future__ import annotations

import pytest

from smurfsniper.api.sc2client.models import GamePlayer
from smurfsniper.api.sc2pulse.ids import MatchType, Queue
from smurfsniper.api.sc2pulse.models import LadderDistinctCharacter
from smurfsniper.core.matching import (
    identify_me,
    match_type_for,
    pick_candidate,
    queue_for,
)
from smurfsniper.core.profile import GameSeed


def cand(
    cid: int,
    name: str,
    region: str = "EU",
    rating: int | None = 3000,
    races: dict | None = None,
    games: int | None = 10,
) -> LadderDistinctCharacter:
    return LadderDistinctCharacter.model_validate(
        {
            "currentStats": {"rating": rating, "gamesPlayed": games},
            "members": {
                "character": {
                    "id": cid,
                    "accountId": cid,
                    "region": region,
                    "realm": 1,
                    "battlenetId": cid,
                    "name": name,
                },
                "raceGames": races or {"ZERG": 10},
            },
        }
    )


SEED = GameSeed("Bob", "ZERG")


def test_exact_name_required():
    assert pick_candidate([cand(1, "Bobby#1")], SEED, region="EU", my_mmr=3000) is None
    got = pick_candidate([cand(1, "bob#12")], SEED, region="EU", my_mmr=3000)
    assert got is not None and got[0].members.character.id == 1


def test_region_bonus_dominates():
    cands = [cand(1, "Bob#1", region="US", rating=3000), cand(2, "Bob#2", region="EU", rating=3700)]
    best, conf = pick_candidate(cands, SEED, region="EU", my_mmr=3000)
    # EU (+6, outside window) beats US (+3 window)
    assert best.members.character.id == 2
    assert 0 < conf < 1


def test_window_and_widening():
    in_window = [cand(1, "Bob#1", rating=3400), cand(2, "Bob#2", rating=5000)]
    best, conf = pick_candidate(in_window, SEED, region=None, my_mmr=3000)
    assert best.members.character.id == 1
    assert conf == pytest.approx(1.0)

    far = [cand(1, "Bob#1", rating=3800), cand(2, "Bob#2", rating=6000)]
    best_w, conf_w = pick_candidate(far, SEED, region=None, my_mmr=3000, window=500)
    assert best_w.members.character.id == 1  # within 2*window
    assert conf_w == pytest.approx(1.0 - 0.15)


def test_runner_up_penalty():
    cands = [cand(1, "Bob#1", rating=3100), cand(2, "Bob#2", rating=3050)]
    best, conf = pick_candidate(cands, SEED, region="EU", my_mmr=3000)
    assert best.members.character.id == 1  # tie -> higher rating
    assert conf == pytest.approx(1.0 - 0.2)


def test_race_and_activity():
    cands = [
        cand(1, "Bob#1", races={"TERRAN": 50}, games=None),
        cand(2, "Bob#2", races={"ZERG": 5}, games=4, rating=2900),
    ]
    best, _ = pick_candidate(cands, SEED, region=None, my_mmr=None)
    assert best.members.character.id == 2


def test_identify_me_and_queues():
    ps = [GamePlayer(id=1, name="Me"), GamePlayer(id=2, name="me", type="computer")]
    assert identify_me(ps, "ME#123").id == 1
    assert identify_me(ps, None) is None
    assert queue_for("2v2") is Queue.LOTV_2V2 and queue_for("other") is Queue.LOTV_1V1
    assert match_type_for("4v4") is MatchType._4V4
