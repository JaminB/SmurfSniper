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
- Global hotkeys: see the **Hotkeys** table below. Overlays are click-through, so every panel is
  dismissed by pressing its hotkey again or the hide-all key; each panel shows its hotkey as a
  chip in its header, and a hint pill lists the hotkeys at game start.

## Hotkeys

Registered with the `keyboard` library, rebindable in Settings > Hotkeys (stored in
`hotkeys.*`), shown in the tray cheat-sheet.

| Default | Config key | Action |
|---|---|---|
| `Ctrl+Shift+1` | `opponent_card` | Toggle the opponent card (cached data only) |
| `Ctrl+Shift+2` | `intel` | Toggle the scouting-intel panel (pro info, tendencies, every smurf reason) |
| `Ctrl+Shift+3` | `session` | Toggle the session tracker panel |
| `Ctrl+Shift+4` | `rivals` | Toggle the rivals / nemesis panel (local DB only) |
| `Ctrl+Shift+R` | `redetect` | Re-detect the current game (new game id on the next in-game poll) |
| `Ctrl+Shift+`` | `hide_all` | Hide / show every overlay (resets on the next game) |

One panel is visible at a time: another panel's hotkey swaps it. No hotkey makes a network call;
panels read cached profiles, the in-memory session or the local SQLite log.

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
   └─ on game_ended: PlayerLogStore.record_game on a writer thread, then
      AccountService.refresh_mmr_after_game (20 s / 90 s / 300 s retries)

EventBus.game_started/game_ended + AccountService.mmr_refreshed (main thread)
   ├─ SessionTracker (core/session.py): in-memory session + SQLite copy on one worker;
   │     emits game_added -> RecapService (toast, updated in place when the rating lands)
   │     and bus.session_updated -> the open Session panel
   └─ RivalsCache (core/rivals.py): RivalsSummary from the player log, cached until the next game

EventBus + LookupPipeline.update ──> HudController (ui/hud.py, main thread)
   ├─ OpponentCard: one row on GAME, rows inserted as stages land (never empty rows)
   ├─ ToastStack (bus.toast_requested, smurf / SC2Pulse-down / "no intel" notices)
   ├─ PanelHost: one on-demand panel (intel, session, rivals)
   └─ HotkeyHint at game start; visibility rules per GameState (see below)

HotkeyManager (keyboard thread -> triggered signal) -> SmurfSniperApp._on_hotkey
   -> Service.request_redetect (R) | HudController.on_hotkey (everything else)
TrayController / SettingsWindow -> SmurfSniperApp.apply_config(new) -> in-place update of the
shared Config, hotkeys re-bound, clients rebuilt, debounced atomic save (500 ms)
```

Threading contract: the Qt event loop and every widget live on the **main thread**. Network
I/O happens only on the lookup executor and the poller QThread; workers reach the UI only by
emitting signals. `keyboard` callbacks only emit a signal. The transport logs a warning (tests
raise) if a request is made on the GUI thread.

HUD visibility ("auto" = shown without a hotkey): the card and hint auto-show only in
`IN_GAME` (or `REPLAY` with `overlays.show_in_replays`); they are dismissed in menus, loading
and results. Toasts are allowed everywhere except replays. Hotkey panels always work. Hide-all
dismisses everything and drops toasts until a card/panel hotkey is pressed or the next game
starts. The card auto-hides `card.auto_hide_seconds` after its **last** row change; its hotkey
re-shows it from cached profiles (no network) during the game and for 10 minutes after it.
Likely/possible smurfs chime (two-tone / one-tone); a likely smurf also toasts when the card is
not on screen. An SC2Pulse failure on IDENTITY toasts once per game.

## Module map

Top level (`smurfsniper/`):
- `cli.py` — Click CLI: `run`, `validate`, `cache stats|clear`, hidden `self-test` (CI exe
  smoke test: imports every module, loads assets, builds the Settings window and renders
  a full opponent card and the intel panel).
- `service.py` — `Service` (wires poller -> bus -> pipeline, player-log writes, pause, tray
  status text, `request_redetect()`, `game_logged` once a game's opponents are stored). It
  creates no widgets; the HUD subscribes to the bus and the pipeline.
- `textutil.py` — `join`, `duration`, `RACE_LABEL` (no Qt; shared by `core` and `ui.fmt`).
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
- `tray.py` — `TrayController` (`QSystemTrayIcon` + menu; left-click opens the cheat-sheet;
  "Last opponent links" submenu rebuilt from INTEL updates via `set_links()`).
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
  `SmurfInfo`, `TendenciesInfo` (wraps `analyze.tendencies.Tendencies`), `IntelInfo`),
  `LookupUpdate`, `OpponentProfile`.
- `lookup.py` — `LookupPipeline` (executor, stage graph, `ensure()`, `results()`). SMURF also
  fetches `account_characters` (alts) and the per-race summaries in parallel; TENDENCIES reads
  the last 100 matches (`iter_character_matches`, 5 min TTL); H2H tags a rival / nemesis.
- `session.py` — `SessionTracker`: logs each finished ladder game (not vs AI, not custom),
  `mmr_before` captured at game start, `mmr_after` from `AccountService.mmr_refreshed`;
  `current()` is the live `SessionSnapshot` (a session whose last game is over 3 h old reads
  as empty).
- `recap.py` — `RecapService`: post-game toast (`recap-<game_id>`, 10 s) and its in-place MMR
  update within 5.5 min of the game.
- `rivals.py` — `RivalsCache`: `RivalsSummary` read from the log on a worker, cleared on
  `game_ended` / `game_logged`.
- `toasts.py` — `ToastSpec` (so `core` can request toasts without importing `ui`).
- `account.py` — `AccountService`: `identify_me` (configured name, vs-AI, 2-of-3 recent games),
  `search()` -> `AccountCandidate`s, `choose()`, `refresh_mmr_after_game()` /
  `refresh_mmr_now()`. Config mutations are marshalled to the main thread by private signals.

`analyze/` (pure functions; no Qt, httpx, keyboard or peewee):
- `history.py` — `RatingPoint`, `GameOutcome`, `Record`, `Trend`; `rating_points`, `outcomes`
  (from WINS/GAMES deltas), `record`, `season_record`, `trend`, `sparkline`,
  `account_age_days`, `climb_velocity`.
- `smurf.py` — `SmurfInputs`, `SmurfAssessment`, `SmurfReason`, `assess()`, `LEVELS`.
- `h2h.py` — `H2HInfo` (with `rivalry`), `head_to_head(rows)`.
- `intel.py` — `is_distinctive_name`, `should_query_pro_sources`, `aligulac_id`.
- `matches.py` — `RecentResult`, `recent_results` (decided ladder matches, newest first).
- `tendencies.py` — `Tendencies`, `tendencies(matches, character_id, tz=)`: race matchups,
  maps, durations, cheese rate, form, streak, active hours, off-racing (None below 3 matches).
- `session.py` — `SessionSnapshot`, `snapshot(games, mmr_start=)`.
- `rivals.py` — `Rival`, `RivalsSummary`, `rivals(rows)`: top rivals, nemesis, favourite victim.
- `team.py` — `TeamInfo`, `team_summary`, `windowed_records`.

`storage/`:
- `db.py` — `init_db(path)` (WAL, `schema_version` table, `migrate()`).
- `migrations.py` — `m001_initial` (legacy table), `m002_player_log_v2`, `m003_session`
  (`session`, `session_game`).
- `player_log.py` — peewee `PlayerLog` (v2) and `PlayerLogStore` (`record_game`, `rows_for`,
  `all_rows`).
- `session_store.py` — `SessionStore` (`current_session` with the 3 h rollover, `add_game`,
  `set_mmr_after`, `games`, `latest_session`), plain SQL under a write lock.
- `rows.py` — `PlayerLogRow`, `Session`, `SessionGame`, `SessionOpponent` (no peewee import,
  used by `analyze`).

`models/`:
- `config.py` — config **v2** (`Config`, `AccountConfig`, `OverlayConfig`, `HotkeyConfig`,
  `IntegrationsConfig`, `AdvancedConfig`, `Placement`, `Anchor`), `load_config`,
  `save_config` (atomic), `migrate_v1`, `apply_overrides`, `masked_dump`. All models ignore
  unknown keys and validate on assignment.

`ui/` (PySide6; the only place widgets are created):
- `hud.py` — `HudController`: owns the card, toast stack, panel slot and hint; slots
  `on_state`, `on_game_started`, `on_update`, `on_game_ended`, `on_hotkey`, `on_toast`,
  `on_config`; `register_panel(action, title, build_body, ensure=)` (the app registers
  Session and Rivals; `refresh_panel()` rebuilds an open one);
  `set_hidden()` (hide-all), `preview()` (Settings "Preview on screen"),
  `reset_for_new_game()` (stops every timer). Emits `hidden_changed`, `links_changed`.
- `overlay/` — the overlay framework:
  - `base.py` — `OverlayWindow` (frameless, `Tool`, top-most, `WindowTransparentForInput`,
    `WindowDoesNotAcceptFocus`, `WA_ShowWithoutActivating`; `reveal()` fade + slide,
    `dismiss()` fade out and hide, `reposition()`, `set_tokens()`), `Surface` (painted glass:
    rounded fill at the configured opacity, border, 3px race accent bar, drop shadow),
    `anchor_point()` placement (bottom anchors grow upward), `set_animations_enabled()`.
  - `widgets.py` — `Text` (token font, optional elide), `Badge` (smurf / PRO), `Chip`
    (hotkey), `RaceDot`, `Sparkline` (painted bars from the analysis string), `Divider`,
    `Skeleton` (the only allowed placeholder: a pulsing loading row while a stage runs),
    `Row.create()` (returns None when every text part is empty), `Section`, `key_row()`.
  - `card.py` — `OpponentCard` (1v1 full, 2v2 "duo" + `TeamStrip`, 3v3+ compact),
    `OpponentSection` (fixed row order: identity, rating, smurf reasons, trend + records,
    H2H, tendencies; `set_*` only adds rows that have data).
  - `toast.py` — `ToastSpec`, `Toast`, `ToastStack` (newest at the anchor edge, same `id`
    replaces in place and resets its timer, `max_visible`).
  - `panel.py` — `Panel` (title + `[hotkey ✕]` chip header, `set_body`, `set_loading`),
    `PanelHost` (one slot: a panel's hotkey toggles it, another panel's swaps it).
  - `hint.py` — `HotkeyHint` pill (full list for the first 5 games of a run, then hide + card).
- `panels/intel.py` — `build_intel_body()` (pro, Aligulac, earnings, Liquipedia extract, every
  smurf reason, Tendencies: form, vs races, maps, length, usual hours, off-race; link types)
  and `links_of()` for the tray menu.
- `panels/session.py` — `build(snapshot, tokens)`: record, MMR movement, sparkline, streak,
  time played, per-matchup records; the empty state is one row.
- `panels/rivals.py` — `build(summary, tokens)`: nemesis / victim lines and the rivals list.
- `fmt.py` — pure text helpers (league, top %, records, H2H, tendencies, flags, Aligulac);
  each returns None instead of a placeholder.
- `preview_data.py` — typed fake profiles, session games and rivals used by previews and tests.
- `tokens.py` — design tokens (colours, radii, fonts, sizes, paddings, animation timings, smurf
  and PRO badge colours) and `TokenContext(opacity, scale, screen)` with `px()`; `theme.py` —
  QSS for normal windows built from the tokens.
- `frameless.py` — `FramelessDialog` (rounded, draggable, Esc closes).
- `account_picker.py` — `AccountPickerDialog` (debounced search, candidate rows).
- `cheatsheet.py` — `HotkeyCheatSheet` (hotkey chips; closes on Esc / focus loss).
- `settings/` — `SettingsWindow` (left nav, instant apply, no Save button) and the tabs
  `tab_account.py`, `tab_overlays.py`, `tab_hotkeys.py`, `tab_integrations.py`,
  `tab_advanced.py`; `widgets.py` has `ChipLabel`, `ToggleSwitch`, `AnchorGrid`,
  `ScreenPreview`, `ChipList`, `SettingsHooks` (callbacks the app supplies).

## Smurf detection heuristic

`analyze/smurf.py::assess` computes a graded **0-100 smurf score** with reasons; levels:
score ≥ 70 → "likely", ≥ 45 → "possible", ≥ 25 → "suspicious". The total is capped at 100.

| code | rule | points |
|---|---|---|
| `wr3d` | 3-day winrate ≥ 80% with 5+ games | +35 |
| `wr7d` | 7-day winrate ≥ 75% with 8+ games | +25 |
| `wrlife` | lifetime winrate ≥ 70% with 30+ games | +15 |
| `age` | account ≤ 14 days (+30) or ≤ 30 days (+18) | +30 / +18 |
| `climb` | lifetime-average climb ≥ 15 MMR/day (+20) or ≥ 8 (+10) | +20 / +10 |
| `alt_peak` | another character of the same account peaked ≥ 800 above the current MMR, or ≥ 400; only the strongest alt counts | +35 / +20 |
| `peak_gap` | peak league ≥ 3 above the current one or peak MMR ≥ 1200 above; or ≥ 2 leagues / ≥ 700 MMR; not cumulative | +25 / +15 |
| `off_race` | current race < 20% of games, main race 100+ games: its peak ≥ current + 300, otherwise | +20 / +8 |

`age` and `climb` need ≥ 5 rating points. `alt_peak`, `peak_gap` and the higher-peak
`off_race` need a known `current_mmr`. Reasons sort by points; the card shows the top 2, the
intel panel all of them. Win/loss comes from SC2Pulse WINS/GAMES counters per team and season
(rating-delta sign only as a fallback). Alts come from `/characters?accountId=` (cached 1 h);
`character-links` is for socials only.

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
  points plus `offset_x` / `offset_y` px at scale 1.0). `card.enabled` only controls the
  automatic show (the hotkey still works), `card.auto_hide_seconds` (0 = stay all game),
  `toasts.seconds` / `max_visible`, `hint.seconds`; `panels` places every on-demand panel.
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
- Sessions: `session` / `session_game` tables in the same DB. A new session starts after a 3 h
  gap between games; each game keeps `mmr_before` / `mmr_after` (filled when SC2Pulse reports
  the new rating) and its opponents as JSON.
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
- HUD previews: `python scripts/render_preview.py [--out previews] [--only card]` renders every
  overlay component offscreen at scales 1.0 and 1.25 (gitignored `previews/`). Overlay code
  takes sizes and colours only from `ui/tokens.py` via `TokenContext`; text comes from
  `ui/fmt.py` helpers that return None, and rows are built with `Row.create()` so missing data
  never takes space.
- Overlay callbacks: connect timers and animations to bound methods or widget signals, not
  lambdas that capture the owning window (a Python reference cycle crashed on GC).
- `config.yaml` is gitignored. Never commit API keys; the CLI masks the Aligulac key.
