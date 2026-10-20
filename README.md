# SmurfSniper 🎯

<p align="center">
  <a href="https://github.com/JaminB/smurfsniper/releases/latest">
    <img
      src="https://img.shields.io/github/v/release/JaminB/smurfsniper?style=for-the-badge&label=Download%20.exe&logo=windows&color=2ea44f"
      alt="Download latest release"
    />
  </a>
  <a href="https://buymeacoffee.com/jaminbeckes">
    <img
      src="https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black"
      alt="Buy Me a Coffee"
    />
  </a>
</p>

<p align="center">
  <b><a href="https://github.com/JaminB/smurfsniper/releases/latest">⬇️ Download the latest <code>smurfsniper-&lt;version&gt;-windows-x64.exe</code></a></b> — no Python required.
</p>

**SmurfSniper** is a real-time **StarCraft II** overlay and analysis tool. It watches your
matches as they start, looks up every opponent on the community **SC2Pulse** database, analyzes
their MMR trend and win-rate history, and renders in-game overlays that flag accounts which look
a little too good for their stated rank. Every opponent you meet is logged locally, so the next
time you queue into them you see your head-to-head history at a glance.

<p align="center">
  <img
    src="img/logo.png"
    alt="Smurf Sniper logo"
    width="420"
  />
</p>

---

## Features

### Real-time match detection
- Polls the **local SC2 client API** (`http://localhost:6119`, `/ui` and `/game`) every
  **1.5 seconds** on a background thread, so the overlay never freezes.
- Tracks the client state (menu, loading, in game, replay, score screen), so an immediate
  **rematch** against the same player is detected, **replays** and **vs-AI** games trigger no
  lookups, and the game result is logged once within ~1.5 s of the game ending.
- When SC2 is closed it logs a single "SC2 client offline" line and polls every 10 s.
- Supports ranked **1v1**, **2v2**, and team (**3v3 / 4v4**) games.

### Opponent intelligence (SC2Pulse)
- Looks up each opponent's ladder profile, current-season team, league and tier, regional
  rank, peak MMR, full rating history and recent matches.
- Candidates must match the in-game name exactly; they are ranked by your **±500 MMR window**
  (your MMR, kept up to date automatically; widened to ±1000 if nobody fits), the race seen in game and recent activity.
- Lookups run in stages. The opponent card appears with just the name and race within a
  moment of the game starting and **grows a row at a time** as rating, smurf analysis,
  head-to-head and tendencies arrive.
- Responses are cached in memory and on disk (SQLite) with per-endpoint lifetimes, so a
  rematch or a hotkey never re-downloads what was already fetched. A cold 1v1 lookup costs at
  most 7 SC2Pulse requests; a warm one costs none.

### MMR & form analysis
- **MMR trend** via linear regression (MMR per day) over the last **100 rating points**.
- **Sparklines** (`▁▂▃▄▅▆▇█`) summarizing the last 30 days of MMR movement.
- **Win/loss windows** for the last **3 days, 7 days, 30 days and the current season**, counted
  from SC2Pulse's real win and game counters (only windows with games are shown).

### Smurf detection
- Graded **0–100 smurf score** with human-readable reasons, mapped to a label:
  - **≥ 70 → ⚠️ Likely Smurf**
  - **≥ 45 → ⚠️ Possible Smurf**
  - **≥ 25 → ⚠️ Suspiciously strong**
- Score contributions (capped at 100):
  - 3-day win rate ≥ 80% with 5+ games → **+35**
  - 7-day win rate ≥ 75% with 8+ games → **+25**
  - lifetime win rate ≥ 70% with 30+ games → **+15**
  - new account ≤ 14d → **+30**, or ≤ 30d → **+18** (needs ≥ 5 games)
  - MMR climb ≥ 15/day → **+20**, or ≥ 8/day → **+10**
- The graded model flags a brand-new, fast-climbing account **before** its win-rate window even
  fills.

### Head-to-head history
- Every opponent encounter is written to a local **SQLite** database.
- On future runs, the opponent card shows your **record vs. that opponent** (e.g. `You 3-1 ·
  2d ago`).
- Each row stores the game mode, both races, game length and your own result, and a game is
  never logged twice. Older databases are migrated automatically.

### Scouting intel (Ctrl+Shift+2)
On demand, show a deeper scouting profile on the current opponent(s), using official public
APIs only:
- **Recent form** (last 10 results), **top maps** with W-L records and **average game length**
  from their SC2Pulse match history.
- **Pro details** from SC2Pulse (team, country, earnings) and the links they have registered
  there (Liquipedia, Twitch, Aligulac, ...).
- **Aligulac** rating and rank (needs a free API key) and the **Liquipedia** intro, looked up
  only for revealed pros or names distinctive enough to be worth it.

### Tray app and Settings
- SmurfSniper lives in the **system tray**: no console window, logs go to a file. Left-click
  the icon for the hotkey cheat-sheet; right-click for the menu (Hotkeys, Settings, Change
  account, Last opponent links, Pause lookups, Hide HUD, Sounds, open the logs or data folder,
  Quit). *Last opponent links* opens the Liquipedia / Twitch / Aligulac pages found by
  scouting intel (overlays are click-through, so links live in the tray).
- A modern **Settings window** (dark, instant apply, no Save button) with five tabs: Account,
  Overlays, Hotkeys, Integrations and Advanced. No YAML editing is needed.
- **Auto-detected account**: SmurfSniper learns your in-game name from the games you play,
  finds your SC2Pulse character and **refreshes your MMR after every game** (it polls SC2Pulse
  20 s, 90 s and 5 min after the game until the rating moves). On first run a small picker lets
  you choose your account; "Detect automatically" skips it.
- Only one instance runs at a time; a second launch exits with a notice.

### HUD
A compact, glass-style HUD that only takes space for information that exists:
- **Opponent card** (top centre by default, at most about 320x170 px for a 1v1): name, clan,
  region and race badge first, then MMR, league and regional rank, a colour-coded smurf badge
  (`SUSPICIOUS` / `POSSIBLE SMURF` / `LIKELY SMURF` + score) with its top reasons, MMR trend
  bars with recent records, your head-to-head record and their win rate vs. your race. Rows
  with no data are never drawn. 2v2 adds a team strip; 3v3/4v4 use one line per opponent.
  It fades out 45 s after its last update and its hotkey brings it back from cache.
- **Toasts** (top right): small notices that fade on their own, e.g. a likely smurf when the
  card is hidden, or SC2Pulse being unreachable.
- **Panels** on demand (scouting intel now; session and rivals later). Each panel's header
  shows its hotkey as a chip, and the same hotkey closes it.
- A **hotkey hint** pill at the start of a game lists the hotkeys (shortened after 5 games).
- Race-coloured accent bars, fade/slide animations, adjustable opacity and scale. Nothing
  shows in menus or replays except toasts and panels you ask for.

### Configurable overlays
- Frameless, transparent, **always-on-top** and **click-through** widgets that never take
  the mouse or keyboard focus.
- Opacity (40-100%) and size (75-150%) sliders, a screen selector, and per-surface placement:
  a 3x3 anchor grid plus X/Y offsets for the opponent card, toasts, panels and hotkey hint.
  *Preview on screen* shows samples at the configured spots.
- Overlays appear above SC2 in **Windowed (Fullscreen)** or windowed mode, **not** in
  exclusive fullscreen.

### Hotkeys
Global hotkeys, all rebindable in **Settings > Hotkeys** (no restart) and listed in the tray
cheat-sheet. Overlays are click-through, so press a panel's hotkey again (or the hide-all key)
to dismiss it.

| Default | Action |
|---|---|
| **Ctrl+Shift+1** | Opponent card (toggle; re-shows from cached data, no new requests) |
| **Ctrl+Shift+2** | Scouting intel: form, maps, pro details, Aligulac, Liquipedia (toggle) |
| **Ctrl+Shift+3** | Session tracker (coming in a later release) |
| **Ctrl+Shift+4** | Rivals (coming in a later release) |
| **Ctrl+Shift+R** | Re-detect the current game |
| **Ctrl+Shift+`** | Hide / show everything (resets on the next game) |

SC2 still receives these keys. Avoid combos bound in your SC2 hotkey profile; Settings warns
about the usual SC2 ones. On Windows with several input languages, Ctrl+Shift alone switches
the keyboard layout; that is harmless with a third key. If SC2 runs **as administrator**, run
SmurfSniper as administrator too, or the hooks will not see the keys. On non-US layouts the
backtick key may not be available; rebind it in Settings.

### Other
- **Audio chimes** (Windows `winsound`) signal new games and notable findings.
- Settings are stored in `config.yaml` in the platformdirs **user config dir** (or `--config`).
  Old (v1) config files are migrated automatically and backed up as `config.v1.bak.yaml`.
- A rotating `app.log` (10 MB, 14-day retention) in the user log directory
  (`%LOCALAPPDATA%\smurfsniper\smurfsniper\Logs` on Windows); the CLI also logs to the console.
- Optional **Aligulac API key** integration for richer pro-player data. The key is never logged
  or printed in full.
- Distributed as a self-contained **Windows `.exe`** (no Python required) via the release build.

---

## Requirements

- **Windows** (overlays and audio are Windows-first).
- **StarCraft II** running locally.
- Internet access for SC2Pulse / scouting lookups.
- Python **3.13–3.14** — only if running from source (the `.exe` needs nothing installed).

---

## Installation

### Option A — Download the executable
Grab the latest `smurfsniper-<version>-windows-x64.exe` from the
[**latest release**](https://github.com/JaminB/smurfsniper/releases/latest) and run it.
No Python install required.

### Option B — From source

```bash
git clone https://github.com/JaminB/smurfsniper.git
cd smurfsniper
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
pip install .
```

---

## Configuration

Open **Settings** from the tray icon. Everything below can be changed there and applies
instantly. The settings are stored as YAML (version 2) in your user config directory; you can
also point at a file with `--config`.

```yaml
version: 2
account:
  name: YourName            # in-game name, learned automatically
  region: EU
  auto_detect: true
  mmr_by_queue: {201: 4200} # refreshed after each game
  teammates: [TeammateOne]
overlays:
  opacity: 0.7
  scale: 1.0
  card:
    placement: {anchor: top_center, offset_y: 72}
    auto_hide_seconds: 45
hotkeys:
  opponent_card: ctrl+shift+1
  hide_all: ctrl+shift+`
integrations:
  aligulac_api_key: ""      # optional, free: https://aligulac.com/about/api/
  liquipedia_enabled: true
advanced:
  mmr_window: 500
```

Anchors: `top_left`, `top_center`, `top_right`, `center_left`, `center`, `center_right`,
`bottom_left`, `bottom_center`, `bottom_right`.

---

## Usage

Double-click the `.exe` (or run `smurfsniper`) to start the tray app. From a terminal:

```bash
smurfsniper                                   # tray app
smurfsniper run --no-tray                     # no tray icon; Ctrl+C quits
smurfsniper run --dry-run                     # validate the config, print it, exit
smurfsniper validate --config config.yaml --show
smurfsniper cache stats                       # size of the on-disk API cache
smurfsniper cache clear
```

Printing from the windowed `.exe` attaches to the terminal that launched it, so output may
appear after the prompt returns.

### Common options

| Option | Description |
|---|---|
| `--config PATH` | Path to the config file (default: the user config dir). |
| `--url URL` | SC2 client API base URL (default `http://localhost:6119`; a trailing `/game` is accepted). |
| `--no-tray` | Run without a tray icon. |
| `--dry-run` | Validate the config, print it (API key masked) and exit. |
| `--set KEY=VALUE` | Override a config value in memory (repeatable), e.g. `--set overlays.opacity=0.8`. |
| `--version`, `-V` | Print the version and exit. |

Windows may show a SmartScreen warning for the unsigned `.exe`; choose *More info > Run anyway*.

---

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest            # Qt tests run headless (QT_QPA_PLATFORM=offscreen)
```

Tests never touch the live network; tests marked `live` are opt-in (`pytest -m live`).

Try the app without StarCraft II by running a fake client API that cycles through menu,
loading, in-game and result screens:

```bash
python scripts/fake_sc2.py --port 6119 --script 1v1   # also: 2v2, replay, ai
smurfsniper run --no-tray
```

Render every HUD component (card stages, 2v2, 4v4, toasts, panels, hint and a full-screen
composite) to PNGs at 100% and 125% scale, without a display:

```bash
python scripts/render_preview.py --out previews        # --only card renders just the cards
```

## Data sources

- Data: SC2Pulse (sc2pulse.nephest.com), non-commercial use.
- Pro ratings from [Aligulac](https://aligulac.com) (free API key:
  <https://aligulac.com/about/api/>).
- Player bios from [Liquipedia](https://liquipedia.net/starcraft2) (CC-BY-SA), requested at
  most once every 2 seconds.

## Releases & versioning

- Commits and PR titles follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `ci:`, `refactor:`, `docs:` ...). Squash-merge titles drive the version bump.
- On every push to `main`, [release-please](https://github.com/googleapis/release-please) opens
  (or updates) a release PR that bumps the version in `pyproject.toml` and
  `smurfsniper/_version.py` and updates `CHANGELOG.md`. Merging it tags the release and
  builds the single-file exe, attaching `smurfsniper-<version>-windows-x64.exe`,
  `SHA256SUMS.txt` and a CycloneDX SBOM (`smurfsniper-<version>.cdx.json`).
- Repo setting required: **Settings > Actions > General > "Allow GitHub Actions to create and
  approve pull requests"** must be enabled.
- Optional: add a `RELEASE_PLEASE_TOKEN` personal access token secret. PRs created with the
  default `GITHUB_TOKEN` do not trigger other workflows, so without the PAT the release PR
  will not run CI automatically.
- To rebuild or re-attach assets to an existing release, run the **Build exe** workflow manually
  with the tag and `upload_to_release` enabled.

Verify a download against the published checksum:

```powershell
Get-FileHash -Algorithm SHA256 .\smurfsniper-<version>-windows-x64.exe
# compare with the line in SHA256SUMS.txt
```

## License

MIT License.
