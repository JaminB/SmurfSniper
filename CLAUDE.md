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
smurfsniper                       # tray app (same as `smurfsniper run`)
smurfsniper run [--config PATH] [--url http://localhost:6119] [--no-tray] [--dry-run] [--set KEY=VALUE]
smurfsniper validate [--config PATH] [--show]
smurfsniper cache stats | clear   # on-disk API response cache
smurfsniper --version             # or -V
python scripts/fake_sc2.py --port 6119 --script 1v1     # fake SC2 client for manual testing
```

- `smurfsniper` is a **tray app**: no console window (the frozen exe is built `console=False`),
  logs go to `user_log_dir/app.log`, and settings live in the tray menu. A second instance
  exits with a notice (`QLockFile`).
- Default SC2 client API: `http://localhost:6119` (a trailing `/game` is accepted, `--url` maps
  to `advanced.sc2_client_url`), `/ui` polled every **1.5 s** (10 s while SC2 is offline).
- `--set KEY=VALUE` uses dotted v2 config paths (`--set overlays.opacity=0.8`,
  `--set account.mmr_override=4200`). It applies in memory; the file is only rewritten when
  settings change in the UI (and then includes the override).
- `--dry-run` loads and validates the config, prints it (Aligulac key masked `****abcd`) and exits.
- `--no-tray` runs without a tray icon and quits on Ctrl+C.
- Global hotkeys (`keyboard` lib, rebindable in Settings, defaults `Ctrl+Shift+...`):
  **1** opponent card (toggle), **2** scouting intel (toggle), **3** session tracker and **4**
  rivals (reserved for a later branch), **R** re-detect game (new game id on the next in-game
  poll), **`** hide/show all (resets on the next game). Overlays are click-through, so every
  panel is dismissed by pressing its hotkey again or the hide-all key.

## Architecture

```
Sc2ClientPoller (own QThread) ── /ui + /game ──> GameStateMachine
   │ state_changed / game_started / game_ended (queued signals)
   v
EventBus (main thread) ──> Service            SmurfSniperApp (app/application.py)
   ├─ AccountService (core/account.py): identify me, MMR refresh   owns QApplication, tray,
   ├─ LookupPipeline.start(ctx)   (ThreadPoolExecutor, all network I/O)
   │     GAME -> IDENTITY -> RATING / SMURF / H2H / TENDENCIES / INTEL, TEAM for 2v2+
   │     update(LookupUpdate) queued to main thread
   ├─ LegacyRenderer.on_update     (ui/legacy_render.py -> legacy Overlay widgets)
   └─ on game_ended: PlayerLogStore.record_game on a writer thread, then
      AccountService.refresh_mmr_after_game (20 s / 90 s / 300 s retries)

HotkeyManager (keyboard thread -> triggered signal) -> SmurfSniperApp._on_hotkey -> Service
TrayController / SettingsWindow -> SmurfSniperApp.apply_config(new) -> in-place update of the
shared Config, hotkeys re-bound, clients rebuilt, debounced atomic save (500 ms)
```

Threading contract: the Qt event loop and every widget live on the **main thread**. Network
I/O happens only on the lookup executor and the poller QThread; workers reach the UI only by
emitting signals. `keyboard` callbacks only emit a signal. The transport logs a warning (tests
raise) if a request is made on the GUI thread.

## Module map

Top level (`smurfsniper/`):
- `cli.py` — Click CLI: `run`, `validate`, `cache stats|clear`, hidden `self-test` (CI exe
  smoke test: imports every module, loads assets, builds the Settings window).
- `service.py` — `Service` (wires poller -> bus -> pipeline -> legacy UI, chimes, pause, hide
  all, tray status text). Hotkey actions arrive as `request_redetect`, `toggle_opponent_card`,
  `toggle_intel`, `toggle_hide_all`.
- `paths.py` — platformdirs locations (`config_dir`, `data_dir`, `cache_dir`, `log_dir`,
  `db_path`, `http_cache_path`, `state_path`, `lock_path`) and `ensure_dirs()`. Nothing
  touches disk at import.
- `logger.py` — loguru `logger` plus `setup_logging(level, *, console)`; rotating file sink at
  `user_log_dir/app.log` (10 MB, 14 days). No console sink when `sys.stderr` is None
  (windowed exe).
- `_version.py`, `_modules.py` (static module list for the frozen self-test; regenerate with
  `python scripts/gen_modules.py`).

`app/` (application shell; may create widgets):
- `application.py` — `SmurfSniperApp`: QApplication, single-instance lock, services, tray,
  hotkey routing, `apply_config()`, picker/settings/cheat-sheet windows, first-run state in
  `user_data_dir/state.json`.
- `tray.py` — `TrayController` (`QSystemTrayIcon` + menu; left-click opens the cheat-sheet).
- `hotkeys.py` — `HotkeyAction`, `DEFAULT_BINDINGS`, `validate_bindings`, `to_display`,
  `from_qkeysequence`, `HotkeyManager` (registers with `suppress=False`, 300 ms debounce, emits
  `triggered` from the keyboard thread).
- `sounds.py` — `SoundPlayer`: cached WAV bytes played by `winsound` on one daemon thread.
- `console.py` — `attach_parent_console()` so `smurfsniper.exe --version` prints in a terminal.

`assets/` — packaged icons (`logo.ico`, `logo.png`, `tray.png`); load with
`smurfsniper.assets.asset_path(name)` (works frozen; the spec ships it via `datas`).

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
- `account.py` — `AccountService`: `identify_me` (configured name, vs-AI, 2-of-3 recent games),
  `search()` -> `AccountCandidate`s, `choose()`, `refresh_mmr_after_game()` /
  `refresh_mmr_now()`. Config mutations are marshalled to the main thread by private signals.

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
- `config.py` — config **v2** (`Config`, `AccountConfig`, `OverlayConfig`, `HotkeyConfig`,
  `IntegrationsConfig`, `AdvancedConfig`, `Placement`, `Anchor`), `load_config`,
  `save_config` (atomic), `migrate_v1`, `apply_overrides`, `masked_dump`. All models ignore
  unknown keys and validate on assignment.

`ui/` (PySide6; the only place widgets are created):
- `overlays.py` — legacy `Overlay` QWidget (frameless, transparent, click-through) with
  anchor + offset placement, plus `show_sample()` for the Settings preview.
- `overlay_manager.py` — `register_overlay()`, `close_all_overlays()`.
- `legacy_render.py` — `LegacyRenderer`: `LookupUpdate`s -> legacy overlays (main, team,
  head-to-head, intel). `toggle(kind)` re-shows/closes from cached profiles (no network),
  `set_hidden()` is the hide-all state. Never renders placeholder rows.
- `tokens.py` — design tokens (colours, radii, fonts, chip style); `theme.py` — QSS for normal
  windows built from the tokens.
- `frameless.py` — `FramelessDialog` (rounded, draggable, Esc closes).
- `account_picker.py` — `AccountPickerDialog` (debounced search, candidate rows).
- `cheatsheet.py` — `HotkeyCheatSheet` (hotkey chips; closes on Esc / focus loss).
- `settings/` — `SettingsWindow` (left nav, instant apply, no Save button) and the tabs
  `tab_account.py`, `tab_overlays.py`, `tab_hotkeys.py`, `tab_integrations.py`,
  `tab_advanced.py`; `widgets.py` has `ChipLabel`, `ToggleSwitch`, `AnchorGrid`,
  `ScreenPreview`, `ChipList`, `SettingsHooks` (callbacks the app supplies).

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
- **Aligulac** `https://aligulac.com/api/v1` — needs `integrations.aligulac_api_key`.
- **Liquipedia** `https://liquipedia.net/starcraft2/api.php` — contactable User-Agent, 1 req/2 s,
  never `action=parse`.
- **Local SC2 client** `http://localhost:6119` — `/ui` and `/game`.
- Twitch GQL and YouTube scraping were removed; use only official/public APIs.

## Config (`config.yaml`, version 2)

Lives at `user_config_dir/config.yaml` (or `--config PATH`); a missing file means defaults and is
not written until the first change. Sections: `account`, `overlays`, `hotkeys`, `integrations`,
`advanced`. Edit it in **Settings** (tray menu); changes apply instantly and are saved
atomically (tmp file + `os.replace`).

- `account`: `character_id`, `toon_handle`, `name` (base name), `region`, `auto_detect`,
  `mmr_by_queue` (`201` = 1v1; auto-refreshed after each game), `mmr_override` (wins when set),
  `teammates` (treated as allies). `mmr_for(queue)`: override > queue > 1v1 > None.
- `overlays`: `opacity` (0.40-1.0), `scale` (0.75-1.5), `screen`, `show_in_replays`, and
  `card` / `toasts` / `hint` / `panels` blocks, each with a `placement` (`anchor` one of nine
  points plus `offset_x` / `offset_y` px at scale 1.0). The legacy overlays use `card` for the
  opponent card and team, `toasts` for head-to-head and `panels` for intel.
- `hotkeys`: `opponent_card`, `intel`, `session`, `rivals`, `redetect`, `hide_all` (strings in
  the `keyboard` library format, e.g. `ctrl+shift+1`) and `enabled`.
- `integrations`: `aligulac_api_key`, `liquipedia_enabled`, `liquipedia_contact`.
- `advanced`: `sc2_client_url`, `ui_poll_ms`, `mmr_window` (default **±500**, widened to ±1000
  with lower confidence when nobody fits), `sounds_enabled`, `log_level` (console and
  `app.log`), `disk_cache`.

**v1 migration**: a file with `me` / `preferences` and no `version` is migrated on load and
the original is copied to `config.v1.bak.yaml`. `me.name`/`me.mmr` -> `account`, `team.members`
-> `account.teammates`, the 1v1 overlay position/duration -> `overlays.card`, the Aligulac key is
kept, the other overlay blocks are dropped (logged) and `integrations.aws_bedrock` is dropped and
never re-written.

Account detection: with `auto_detect` on, the name is learned from a vs-AI game or from a name
present in 2 of the last 3 games (configured teammates never count), then `SC2Pulse` is searched
(auto-chosen when exactly one exact-name character played in the last 7 days; otherwise a tray
balloon offers the picker, prefilled with the name). A name that is already configured but has
no `character_id` (e.g. a migrated v1 config) is searched once per run the first time it is seen
in a game.
The first-run picker (`ui/account_picker.py`) appears only while `account.character_id` is unset
and "Detect automatically" has not been chosen (`state.json`).

## Persistence

- Player log: SQLite at `paths.db_path()` (user data dir), schema-versioned; opened by
  `storage.db.init_db()` at service start. One row per opponent per game, written on game end
  (idempotent on `game_uid`).
- HTTP cache: SQLite at `paths.http_cache_path()` (user cache dir), pruned on startup.
- `state.json` in the user data dir: `first_run_done`, `picker_skipped`.
- Single-instance lock: `paths.lock_path()` (system temp dir) via `QLockFile`.

## Conventions / gotchas

- Tests: `QT_QPA_PLATFORM=offscreen python -m pytest -q`; lint: `ruff check .` and
  `ruff format --check .`. Tests never hit the live network (respx + `tests/fixtures`).
- `tests/test_architecture.py` enforces the layering rules above; keep it green.
- Datetimes are timezone-aware UTC (`datetime.now(UTC)`), never `utcnow()`.
- After adding or removing a module, run `python scripts/gen_modules.py`
  (`test_modules_list_complete` checks it).
- **Windows-only audio** (`winsound`); `SoundPlayer` is a no-op elsewhere.
- The exe is windowed (`console=False`): `sys.stdout`/`sys.stderr` can be None, so never
  `print()`; use `logger` or `click.echo`. `packaging/pyi_entry.py` attaches the parent console
  when arguments are given.
- Never import `PySide6.QtNetwork` (excluded from the exe; `QLockFile` is QtCore).
- `keyboard` callbacks may only emit a signal. Overlays are click-through and only appear above
  SC2 in Windowed (Fullscreen) or windowed mode, not exclusive fullscreen.
- `scripts/make_version_file.py` writes the Windows version resource used by the spec.
- `config.yaml` is gitignored. Never commit API keys; the CLI masks the Aligulac key.
