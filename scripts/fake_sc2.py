#!/usr/bin/env python3
"""Tiny stand-in for the StarCraft II client API, for manual testing.

Serves ``/game`` and ``/ui`` from ``tests/fixtures`` and cycles through
menu -> loading -> in-game -> result -> menu on a timer.

    python scripts/fake_sc2.py --port 6119 --script 1v1
    python scripts/fake_sc2.py --script 2v2 --in-game 60
    python scripts/fake_sc2.py --script replay
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

SCRIPTS = {
    "1v1": "game_1v1",
    "2v2": "game_2v2",
    "replay": "game_replay",
    "ai": "game_vs_ai",
}


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def with_result(game: dict, me: str | None) -> dict:
    """Mark the game finished: ``me`` (or player 1) wins, everybody else loses."""
    players = []
    for i, p in enumerate(game["players"]):
        won = p["name"] == me if me else i == 0
        players.append({**p, "result": "Victory" if won else "Defeat"})
    return {**game, "players": players, "displayTime": 600.0}


class Phases:
    def __init__(
        self,
        game: dict,
        *,
        menu: float,
        loading: float,
        in_game: float,
        result: float,
        me: str | None,
    ):
        self.timeline = [
            ("menu", menu, load("ui_menu"), load("game_menu")),
            ("loading", loading, load("ui_loading"), load("game_menu")),
            ("in_game", in_game, load("ui_ingame"), game),
            ("result", result, load("ui_score"), with_result(game, me)),
        ]
        self.total = sum(t for _, t, _, _ in self.timeline)
        self.t0 = time.monotonic()
        self._last = None

    def current(self) -> tuple[str, dict, dict]:
        t = (time.monotonic() - self.t0) % self.total
        for name, dur, ui, game in self.timeline:
            if t < dur:
                if name != self._last:
                    print(f"[fake_sc2] phase: {name}", flush=True)
                    self._last = name
                return name, ui, game
            t -= dur
        name, _, ui, game = self.timeline[-1]
        return name, ui, game


def make_handler(phases: Phases):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            _, ui, game = phases.current()
            if self.path.rstrip("/") == "/ui":
                body = ui
            elif self.path.rstrip("/") == "/game":
                body = game
            else:
                self.send_error(404)
                return
            data = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args) -> None:
            pass

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--port", type=int, default=6119)
    ap.add_argument("--script", choices=sorted(SCRIPTS), default="1v1")
    ap.add_argument("--me", default="Me", help="name that wins the game (default: Me)")
    ap.add_argument("--menu", type=float, default=5.0, help="seconds in menus")
    ap.add_argument("--loading", type=float, default=3.0)
    ap.add_argument("--in-game", type=float, default=30.0)
    ap.add_argument("--result", type=float, default=5.0)
    args = ap.parse_args(argv)

    phases = Phases(
        load(SCRIPTS[args.script]),
        menu=args.menu,
        loading=args.loading,
        in_game=args.in_game,
        result=args.result,
        me=args.me,
    )
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(phases))
    print(f"[fake_sc2] serving {args.script} on http://127.0.0.1:{args.port} (ctrl+c to stop)")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
