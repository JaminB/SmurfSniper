from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from enum import Enum, IntEnum

from smurfsniper.api.params import build_params


class Color(Enum):
    RED = "r"


class Queue(IntEnum):
    __param_by_name__ = True
    LOTV_1V1 = 201


def test_drops_none_and_keeps_order():
    assert build_params(b=1, a=None, c="x") == [("b", "1"), ("c", "x")]


def test_repeated_keys_for_sequences():
    assert build_params(characterId=[1, 2, 3]) == [
        ("characterId", "1"),
        ("characterId", "2"),
        ("characterId", "3"),
    ]
    assert build_params(t=(1,)) == [("t", "1")]


def test_never_comma_joins():
    pairs = build_params(x=["a", "b"])
    assert all("," not in v for _, v in pairs)
    assert len(pairs) == 2


def test_bool_datetime_enum():
    dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert build_params(flag=True, off=False) == [("flag", "true"), ("off", "false")]
    assert build_params(when=dt) == [("when", "2026-01-02T03:04:05Z")]
    other = dt.astimezone(timezone(timedelta(hours=2)))
    assert build_params(when=other) == [("when", "2026-01-02T03:04:05Z")]
    assert build_params(c=Color.RED) == [("c", "r")]
    assert build_params(q=Queue.LOTV_1V1) == [("q", "LOTV_1V1")]
    assert build_params(q=[Queue.LOTV_1V1]) == [("q", "LOTV_1V1")]


def test_trailing_underscore_stripped():
    assert build_params(from_=1) == [("from", "1")]
