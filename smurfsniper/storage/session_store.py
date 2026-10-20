"""Play sessions and their games (``session`` / ``session_game`` tables).

A session is a run of games with no gap longer than ``SESSION_GAP`` between two games.
Writes are serialised by a lock; every call opens its own connection context, so the
store is safe to use from worker threads.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from peewee import SqliteDatabase

from smurfsniper.storage.rows import Session, SessionGame, SessionOpponent

if TYPE_CHECKING:
    from smurfsniper.core.game_state import GameResult
    from smurfsniper.core.profile import OpponentProfile

SESSION_GAP = timedelta(hours=3)
_write_lock = threading.Lock()
_GAME_COLUMNS = (
    "id, session_id, game_uid, started_at, ended_at, mode, my_race, my_result, "
    "opponents, mmr_before, mmr_after, game_seconds"
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _parse(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def opponents_of(
    result: GameResult, profiles: Mapping[int, OpponentProfile]
) -> tuple[SessionOpponent, ...]:
    """Human opponents of ``result`` with whatever the lookups resolved."""
    out: list[SessionOpponent] = []
    for slot, seat in enumerate(result.context.opponents):
        if not seat.is_human:
            continue
        prof = profiles.get(slot)
        ident = prof.identity if prof else None
        mmr = None
        if prof is not None and prof.rating is not None and prof.rating.mmr:
            mmr = prof.rating.mmr
        out.append(
            SessionOpponent(
                name=ident.character.base_name if ident else seat.name.split("#")[0],
                race=seat.race_code,
                character_id=ident.character.id if ident else None,
                mmr=mmr,
            )
        )
    return tuple(out)


def _game(row: Sequence) -> SessionGame:
    (gid, sid, uid, start, end, mode, race, res, opps, before, after, secs) = row
    try:
        opponents = tuple(SessionOpponent(**o) for o in json.loads(opps))
    except (ValueError, TypeError):
        opponents = ()
    return SessionGame(
        id=gid,
        session_id=sid,
        game_uid=uid,
        started_at=_parse(start),
        ended_at=_parse(end),
        mode=mode,
        my_race=race,
        my_result=res,
        opponents=opponents,
        mmr_before=before,
        mmr_after=after,
        game_seconds=secs,
    )


class SessionStore:
    def __init__(self, db: SqliteDatabase):
        self.db = db

    # --------------------------------------------------------------- sessions
    def current_session(
        self, now: datetime | None = None, *, character_id: int | None = None
    ) -> Session:
        """The open session, or a new one when there is none or the last game is >3 h old."""
        now = now or datetime.now(UTC)
        with _write_lock, self.db.connection_context():
            return self._current(now, character_id)

    def _current(self, now: datetime, character_id: int | None) -> Session:
        row = self.db.execute_sql(
            "SELECT s.id, s.started_at, s.ended_at, s.character_id, "
            "(SELECT MAX(g.ended_at) FROM session_game g WHERE g.session_id = s.id) "
            "FROM session s ORDER BY s.id DESC LIMIT 1"
        ).fetchone()
        if row is not None and row[2] is None:
            last = _parse(row[4]) if row[4] else _parse(row[1])
            if now - last <= SESSION_GAP:
                return Session(row[0], _parse(row[1]), None, row[3])
            self.db.execute_sql(
                "UPDATE session SET ended_at = ? WHERE id = ?", (_iso(last), row[0])
            )
        cur = self.db.execute_sql(
            "INSERT INTO session (started_at, ended_at, character_id) VALUES (?, NULL, ?)",
            (_iso(now), character_id),
        )
        return Session(cur.lastrowid, now, None, character_id)

    # ------------------------------------------------------------------ games
    def add_game(
        self,
        result: GameResult,
        profiles: Mapping[int, OpponentProfile],
        mmr_before: int | None,
        *,
        uid: str,
        now: datetime | None = None,
        character_id: int | None = None,
    ) -> SessionGame:
        """Insert a game (idempotent per ``uid``) into the current session."""
        now = now or datetime.now(UTC)
        ctx = result.context
        opponents = opponents_of(result, profiles)
        secs = int(result.display_time) if result.display_time else None
        opp_json = json.dumps(
            [
                {"name": o.name, "race": o.race, "character_id": o.character_id, "mmr": o.mmr}
                for o in opponents
            ]
        )
        with _write_lock, self.db.connection_context():
            existing = self.db.execute_sql(
                f"SELECT {_GAME_COLUMNS} FROM session_game WHERE game_uid = ?", (uid,)
            ).fetchone()
            if existing is not None:
                return _game(existing)
            session = self._current(now, character_id)
            self.db.execute_sql(
                "INSERT INTO session_game (session_id, game_uid, started_at, ended_at, mode, "
                "my_race, my_result, opponents, mmr_before, mmr_after, game_seconds) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                (
                    session.id,
                    uid,
                    _iso(ctx.started_at),
                    _iso(now),
                    ctx.mode,
                    ctx.me.race_code if ctx.me else None,
                    result.my_result,
                    opp_json,
                    mmr_before,
                    secs,
                ),
            )
            row = self.db.execute_sql(
                f"SELECT {_GAME_COLUMNS} FROM session_game WHERE game_uid = ?", (uid,)
            ).fetchone()
            return _game(row)

    def set_mmr_after(self, game_uid: str, mmr: int) -> None:
        with _write_lock, self.db.connection_context():
            self.db.execute_sql(
                "UPDATE session_game SET mmr_after = ? WHERE game_uid = ?", (mmr, game_uid)
            )

    def games(self, session_id: int) -> list[SessionGame]:
        """Games of one session, oldest first."""
        with self.db.connection_context():
            cur = self.db.execute_sql(
                f"SELECT {_GAME_COLUMNS} FROM session_game WHERE session_id = ? "
                "ORDER BY ended_at, id",
                (session_id,),
            )
            return [_game(r) for r in cur.fetchall()]

    def latest_session(self) -> Session | None:
        """The newest session without creating one (for startup)."""
        with self.db.connection_context():
            row = self.db.execute_sql(
                "SELECT id, started_at, ended_at, character_id FROM session "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return Session(row[0], _parse(row[1]), _parse(row[2]) if row[2] else None, row[3])
