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
pip install .          # or: pip install -e ".[dev]" for tests + ruff
```

Console entry point: `smurfsniper = "smurfsniper.cli:main"` (Click CLI).

```bash
smurfsniper run --config config.yaml [--url http://localhost:6119] [--headless] [--dry-run] [--set KEY=VALUE]
smurfsniper validate --config config.yaml [--show]
python scripts/fake_sc2.py --port 6119 --script 1v1     # fake SC2 client for manual testing
```

- Default SC2 client API: `http://localhost:6119` (a trailing `/game` is accepted), `/ui`
  polled every **1.5 s** (10 s while SC2 is offline).
- `--set KEY=VALUE` overrides config values in memory (e.g. `--set me.mmr=4200`); the service
  uses that in-memory config.
- `--dry-run` validates config without starting the poll loop.
- Hotkeys (global, `keyboard` lib): **Ctrl+F1** re-detects the game (next in-game poll starts a
  new game id), **Ctrl+F2** shows scouting intel for the current opponents.

## Architecture

```
Sc2ClientPoller (own QThread) ── /ui + /game ──> GameStateMachine
   │ state_changed / game_started / game_ended (queued signals)
   v
EventBus (main thread) ──> Service
   ├─ LookupPipeline.start(ctx)   (ThreadPoolExecutor, all network I/O)
   │     GAME -> IDENTITY -> RATING / SMURF / H2H / TENDENCIES / INTEL, TEAM for 2v2+
   │     update(LookupUpdate) queued to main thread
   ├─ LegacyRenderer.on_update     (ui/legacy_render.py -> legacy Overlay widgets)
   └─ on game_ended: PlayerLogStore.record_game on a writer thread
```

Threading contract: the Qt event loop and every widget live on the **main thread**. Network
I/O happens only on the lookup executor and the poller QThread; workers reach the UI only by
emitting signals. `keyboard` callbacks only emit a signal. The transport logs a warning (tests
raise) if a request is made on the GUI thread.

## Module map

Top level (`smurfsniper/`):
- `cli.py` — Click CLI: `run`, `validate`, hidden `self-test` (CI exe smoke test).
- `service.py` — `Service` (wires poller -> bus -> pipeline -> legacy UI, hotkeys, chimes) and
  `main(url, config, app)`.
- `paths.py` — platformdirs locations (`config_dir`, `data_dir`, `cache_dir`, `log_dir`,
  `db_path`, `http_cache_path`) and `ensure_dirs()`. Nothing touches disk at import.
- `logger.py` — loguru `logger` plus `setup_logging(level, *, console)`; rotating file sink at
  `user_log_dir/app.log` (10 MB, 14 days).
- `sounds.py` — `SoundPlayer`: cached WAV bytes played by `winsound` on one daemon thread.
- `config_paths.py` — config discovery (cwd, then user config dir).
- `_version.py`, `_modules.py` (static module list for the frozen self-test; regenerate with
  `python scripts/gen_modules.py`).

`api/` (one package per service; only `transport.py` and `sc2client/` import httpx):
- `errors.py` — `ApiError`, `NotFound`, `AuthError`, `RateLimited`, `Unavailable`, `BadResponse`.
- `params.py` — `build_params()` (repeated keys, enums by value or name, ISO datetimes).
- `cache.py` — `CachePolicy`, `MemoryCache` (LRU), `DiskCache` (SQLite), `TieredCache`,
  `SingleFlight` (in-flight coalescing).
- `transport.py` — `HttpTransport` (retries, backoff, cache, GUI-thread guard), `TokenBucket`
  (adapts to `RateLimit-*` headers), `RetryPolicy`.
- `registry.py` — `Clients` dataclass and `build_clients(config, ...)`.
- `sc2pulse/` — `ids.py` (Queue, TeamType, League, MatchType, LinkType, column enums,
  `solo_legacy_uid`, `toon_handle`), `models.py` (pydantic models for every endpoint),
  `client.py` (`SC2PulseClient`, every public endpoint, chunking, cursors, TTLs).
- `aligulac/` — `AligulacClient` (player, tag search, ratings, matches, predict,
  `validate_key`); built only when an API key is configured.
- `liquipedia/` — `LiquipediaClient` (opensearch, batched page summaries, search).
- `sc2client/` — `LocalSc2Client` (`game()`, `ui()`), `GamePlayer`, `GameInfo`, `UiInfo`.

`core/` (may import `PySide6.QtCore` only):
- `events.py` — `EventBus(QObject)` signals.
- `game_state.py` — `GameState`, `GameContext`, `GameResult`, pure `GameStateMachine` /
  `derive_state` / `split_teams`, and `Sc2ClientPoller(QObject)`. A UI screen over a running,
  undecided game (in-game menu) stays IN_GAME; a changed roster while IN_GAME is a new game.
- `matching.py` — `pick_candidate()` (exact name required, region, MMR window, confidence),
  `identify_me()`, `queue_for()`, `match_type_for()`.
- `profile.py` — `Stage`, stage dataclasses (`GameSeed`, `Identity`, `RatingInfo`,
  `SmurfInfo`, `TendenciesInfo`, `IntelInfo`), `LookupUpdate`, `OpponentProfile`.
- `lookup.py` — `LookupPipeline` (executor, stage graph, `ensure()`, `results()`).

`analyze/` (pure functions; no Qt, httpx, keyboard or peewee):
- `history.py` — `RatingPoint`, `GameOutcome`, `Record`, `Trend`; `rating_points`, `outcomes`
  (from WINS/GAMES deltas), `record`, `season_record`, `trend`, `sparkline`,
  `account_age_days`, `climb_velocity`.
- `smurf.py` — `SmurfInputs`, `SmurfAssessment`, `SmurfReason`, `assess()`, `LEVELS`.
- `h2h.py` — `H2HInfo`, `head_to_head(rows)`.
- `intel.py` — `is_distinctive_name`, `should_query_pro_sources`, `aligulac_id`.
- `matches.py` — `RecentResult`, `recent_results`, `map_records`, `avg_duration`.
- `team.py` — `TeamInfo`, `team_summary`, `windowed_records`.

`storage/`:
- `db.py` — `init_db(path)` (WAL, `schema_version` table, `migrate()`).
- `migrations.py` — `m001_initial` (legacy table), `m002_player_log_v2`.
- `player_log.py` — peewee `PlayerLog` (v2) and `PlayerLogStore` (`record_game`, `rows_for`,
  `all_rows`).
- `rows.py` — `PlayerLogRow` (no peewee import, used by `analyze`).

`models/`:
- `config.py` — `Config`, `Preferences`, `OverlayPreferences`, `Me`, `Team`, `Integrations`.

`ui/` (PySide6; the only place widgets are created):
- `overlays.py` — legacy `Overlay` QWidget (frameless, transparent, click-through).
- `overlay_manager.py` — `register_overlay()`, `close_all_overlays()`.
- `legacy_render.py` — `LegacyRenderer`: `LookupUpdate`s -> legacy overlays (main, team,
  head-to-head, Ctrl+F2 intel). Never renders placeholder rows.
- `config_editor.py` — modal config editor shown before `run` (not with `--headless`).

## Smurf detection heuristic

`analyze/smurf.py::assess` computes a graded **0-100 smurf score** with reasons; levels:
score ≥ 70 → "likely", ≥ 45 → "possible", ≥ 25 → "suspicious".

| code | rule | points |
|---|---|---|
| `wr3d` | 3-day winrate ≥ 80% with 5+ games | +35 |
| `wr7d` | 7-day winrate ≥ 75% with 8+ games | +25 |
| `wrlife` | lifetime winrate ≥ 70% with 30+ games | +15 |
| `age` | account ≤ 14 days (+30) or ≤ 30 days (+18) | |
| `climb` | lifetime-average climb ≥ 15 MMR/day (+20) or ≥ 8 (+10) | |

Age and climb need ≥ 5 rating points. Capped at 100. Win/loss now comes from SC2Pulse
WINS/GAMES counters per team and season (rating-delta sign only as a fallback).

## External services

- **SC2Pulse** `https://sc2pulse.nephest.com/sc2/api` — every public endpoint is wrapped in
  `SC2PulseClient`. Rate limit ~4 req/s (token bucket reads `RateLimit-*`). Credit: "Data:
  SC2Pulse (sc2pulse.nephest.com), non-commercial use".
- **Aligulac** `https://aligulac.com/api/v1` — needs `integrations.aligulac.api_key`.
- **Liquipedia** `https://liquipedia.net/starcraft2/api.php` — contactable User-Agent, 1 req/2 s,
  never `action=parse`.
- **Local SC2 client** `http://localhost:6119` — `/ui` and `/game`.
- Twitch GQL and YouTube scraping were removed; use only official/public APIs.

## Config (`config.yaml`)

Top-level keys: `me`, `team`, `preferences`, `integrations` (unchanged in this branch).

Overlay preference blocks under `preferences`: `1v1_overlay`, `2v2_overlay`, `team_overlay`,
`overlay_player_log_1`, `overlay_player_log_2`, optional `external_overlay` (Ctrl+F2). Each has
`visible`, `orientation` (horizontal|vertical), `position`, `seconds_delay_before_show`,
`seconds_visible`. `position`: top_left/top_right/bottom_left/bottom_right/top_center/
bottom_center/center.

`me.name` identifies you among the in-game players; `me.mmr` centres the **±500 MMR** candidate
window (widened to ±1000, with lower confidence, when nobody fits). `team.members` names are
treated as allies.

## Persistence

- Player log: SQLite at `paths.db_path()` (user data dir), schema-versioned; opened by
  `storage.db.init_db()` at service start. One row per opponent per game, written on game end
  (idempotent on `game_uid`).
- HTTP cache: SQLite at `paths.http_cache_path()` (user cache dir), pruned on startup.

## Conventions / gotchas

- Tests: `QT_QPA_PLATFORM=offscreen python -m pytest -q`; lint: `ruff check .` and
  `ruff format --check .`. Tests never hit the live network (respx + `tests/fixtures`).
- `tests/test_architecture.py` enforces the layering rules above; keep it green.
- Datetimes are timezone-aware UTC (`datetime.now(UTC)`), never `utcnow()`.
- After adding or removing a module, run `python scripts/gen_modules.py`
  (`test_modules_list_complete` checks it).
- **Windows-only audio** (`winsound`); `SoundPlayer` is a no-op elsewhere.
- `config.yaml` is gitignored. Never commit API keys; the CLI masks the Aligulac key.
