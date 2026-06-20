# CLAUDE.md

Guidance for Claude Code working in this repo.

## Overview

**smurfsniper** is a real-time **StarCraft II** overlay tool. It polls the local SC2 game
client API for the current match, looks each opponent up on the community **SC2Pulse** API,
analyzes their MMR trend and win rates, and renders frameless in-game overlays that flag
likely **smurf** accounts (high-skill players on low-rank accounts). It also stores every
opponent encounter in a local SQLite DB to show head-to-head history on future runs.

Supports ranked **1v1**, **2v2**, and team (3v3/4v4) formats. Python 3.13–3.14, Poetry build.

## Run / Install

```bash
pip install .          # or: poetry install
```

Console entry point: `smurfsniper = "smurfsniper.cli:main"` (Click CLI).

```bash
smurfsniper run --config config.yaml [--url http://localhost:6119/game] [--dry-run] [--set KEY=VALUE]
smurfsniper validate --config config.yaml [--show]
```

- Default game API: `http://localhost:6119/game`, polled every **5s**.
- `--set KEY=VALUE` overrides config values inline (e.g. `--set me.mmr=4200`).
- `--dry-run` validates config without starting the poll loop.
- Hotkey **Ctrl+F1** resets the game-state detector (forces new-game detection next poll).

## Architecture

Three layers + a polling orchestrator:

```
game API (localhost:6119/game)
  └─ service.py::GamePoller.poll_once()   (every 5s)
       ├─ detect new game + format (state key = (player name, race))
       ├─ models/   fetch opponent data from SC2Pulse
       ├─ analyze/  score it (MMR trend, smurf heuristic, head-to-head)
       └─ ui/       render PySide6 overlays
       on game end → log opponents to PlayerLog (SQLite)
```

Format routing in `GamePoller`: `_handle_1v1()` → `PlayerAnalysis`; `_handle_2v2()` →
`Player2v2Analysis` + `TeamAnalysis`; `_handle_team_game()` → `TeamAnalysis`. Each handler
also pulls `PlayerLogAnalysis` from SQLite and calls `show_overlay()`.

## Module map

Top level (`smurfsniper/`):
- `cli.py` — Click CLI; commands `run`, `validate`.
- `service.py` — `GamePoller`, `main(url, config_file_path)`; the core loop.
- `enums.py` — `Region`, `RaceCode`, `TeamFormat`, `League`, `TeamType`.
- `logger.py` — loguru; colored stdout + rotating `logs/app.log` (10 MB, 14-day retention).
- `utils.py` — `human_friendly_duration()`, `create_team_legacy_uid()`.
- `sounds.py` — `one_tone_chime()`, `two_tone_chime()` (**Windows `winsound`**, Windows-only).

`models/` (Pydantic data + Peewee ORM):
- `config.py` — `Config`, `Preferences`, `OverlayPreferences`, `Me`, `Team`.
- `player.py` — `Player`, `PlayerStats`, `Members`; makes SC2Pulse calls, caches match history.
- `character.py` — `Character` (SC2 profile, `teams` lookup).
- `team.py` — `Team`, `TeamMember`, `TeamLeague`; `.merge()` aggregates seasons/members.
- `team_history.py` — `TeamHistory`, `TeamHistoryPoint`; win/loss windows, sparklines.
- `player_log.py` — `PlayerLog` (Peewee ORM, SQLite), `init_player_log_db()`.
- `shared.py` — `CurrentStats`, `PreviousStats`.

`analyze/` (scoring):
- `__init__.py` — `BaseAnalysis`: MMR trend via linear regression over last 100 games,
  `sparkline()` (▁▂▃▄▅▆▇█), win/loss counts for 1d/3d/7d/30d/lifetime windows.
- `players.py` — `PlayerAnalysis`, `Player2v2Analysis`; smurf detection.
- `teams.py` — `TeamAnalysis`, `NoTeamFound`.
- `player_logs.py` — `PlayerLogAnalysis`; head-to-head record vs an opponent.

`ui/` (PySide6):
- `overlays.py` — `Overlay` QWidget (frameless, transparent, always-on-top); `PLAYER_STYLE`,
  `TM_STYLE`; `add_row()`, `_position_overlay()`; auto-closes after `seconds_visible`.
- `overlay_manager.py` — `register_overlay()`, `close_all_overlays()` (called on new game).
- `qt_thread.py` — `QtThread`, `UiExecutor`, `run_in_ui()`.

## Smurf detection heuristic

`analyze/players.py::PlayerAnalysis._smurf_assessment`
computes a graded **0-100 smurf score** (with reasons); `smurf_warning` maps it
to a label: score ≥ 70 → "⚠️ Likely Smurf", ≥ 45 → "⚠️ Possible Smurf",
≥ 25 → "⚠️ Suspiciously strong".

Score contributions (capped at 100):
- 3-day winrate ≥ 80% with 5+ games → +35
- 7-day winrate ≥ 75% with 8+ games → +25
- lifetime winrate ≥ 70% with 30+ games → +15
- new account ≤ 14d → +30, or ≤ 30d → +18 (needs ≥ 5 games of history)
- MMR climb ≥ 15/day → +20, or ≥ 8/day → +10

This graded model intentionally replaces the earlier fixed three-tier winrate
heuristic so a brand-new, fast-climbing account is flagged even before its
winrate window fills.

## External services

- **SC2Pulse** `https://sc2pulse.nephest.com/sc2/api/` — `characters`, `character-teams`,
  `team-histories` (opponent stats and MMR history).
- **Local SC2 client** `http://localhost:6119/game` — current match state.

## Config (`config.yaml`)

Top-level keys: `me`, `team`, `preferences`, `integrations`.

Overlay preference blocks under `preferences`: `1v1_overlay`, `2v2_overlay`, `team_overlay`,
`overlay_player_log_1`, `overlay_player_log_2`. Each has:
`visible`, `orientation` (horizontal|vertical), `position`, `seconds_delay_before_show`,
`seconds_visible`. `position` is an 8-point screen anchor (top_left/top_right/bottom_left/
bottom_right/top_center/bottom_center/center).

`me.mmr` drives opponent matching: candidates are filtered to a **±500 MMR** window.

## Persistence

SQLite player log in the platformdirs user-data dir. `PlayerLog.init_player_log_db()` runs
on service startup. Opponents are written on game end (skipped if already the most recent log).

## Conventions / gotchas

- **Qt threading**: the QApplication event loop runs in a dedicated thread (`qt_thread.py`).
  Touch widgets only on the UI thread — schedule via `run_in_ui()` / `UiExecutor`.
- **Windows-only audio** (`winsound`); chimes will not work on other platforms.
- No test suite and no linter config currently — add tooling before relying on either.
- `config.yaml` is committed and currently contains a real secret under
  `integrations.aws_bedrock.api_key` — do not commit live keys; prefer env vars / untracked
  files and gitignore the config.
