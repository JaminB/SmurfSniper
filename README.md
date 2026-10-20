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
  (`me.mmr`, widened to ±1000 if nobody fits), the race seen in game and recent activity.
- Lookups run in stages and the overlay appears as soon as identity, rating and history are in.
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
- On future runs, dedicated player-log overlays show your **record vs. that opponent**.
- Each row stores the game mode, both races, game length and your own result, and a game is
  never logged twice. Older databases are migrated automatically.

### Scouting intel (Ctrl+F2)
On demand, show a deeper scouting profile on the current opponent(s), using official public
APIs only:
- **Recent form** (last 10 results), **top maps** with W-L records and **average game length**
  from their SC2Pulse match history.
- **Pro details** from SC2Pulse (team, country, earnings) and the links they have registered
  there (Liquipedia, Twitch, Aligulac, ...).
- **Aligulac** rating and rank (needs a free API key) and the **Liquipedia** intro, looked up
  only for revealed pros or names distinctive enough to be worth it.

### Configurable overlays
- Frameless, transparent, **always-on-top** widgets that **auto-close** after a set duration.
- Independent settings per overlay type: `1v1`, `2v2`, `team`, two **player-log** overlays, and
  the **external** (Ctrl+F2) overlay.
- Per overlay: `visible`, `orientation` (horizontal / vertical), `position` (8-point screen
  anchor), `seconds_delay_before_show`, and `seconds_visible`.
- Lines with no data are left out instead of showing placeholders.

### Config editor GUI
- Double-clicking the executable (or running with no subcommand) launches a **config editor
  dialog** that exposes every option, validates it, saves it, and starts the service.
- `--headless` skips the GUI and loads the resolved config directly.

### Hotkeys
- **Ctrl+F1** — reset the game-state detector (forces new-game detection on the next poll).
- **Ctrl+F2** — pull cross-network scouting intel on the current opponent(s).

### Other
- **Audio chimes** (Windows `winsound`) signal new games and notable findings.
- Config discovery searches the **current directory** first, then the platformdirs **user
  config dir**; new configs are written to the user config dir.
- Colored console logging plus a rotating `app.log` (10 MB, 14-day retention) in the user log
  directory (`%LOCALAPPDATA%\smurfsniper\smurfsniper\Logs` on Windows).
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

SmurfSniper is configured via a YAML file. It is searched for in the current directory first,
then the user config directory. You can also point at one explicitly with `--config`.

### Example `config.yaml`

```yaml
me:
  name: YourBattleTag
  mmr: 4200

team:
  name: Ladder Gremlins
  mmr: 4100
  members:
    - TeammateOne
    - TeammateTwo

preferences:
  1v1_overlay:
    visible: true
    orientation: horizontal
    position: top_center
    seconds_delay_before_show: 0.0
    seconds_visible: 30

  2v2_overlay:
    visible: true
    orientation: horizontal
    position: top_center
    seconds_delay_before_show: 2.0
    seconds_visible: 40

  team_overlay:
    visible: true
    orientation: vertical
    position: top_right
    seconds_delay_before_show: 3.0
    seconds_visible: 45

  overlay_player_log_1:
    visible: true
    orientation: vertical
    position: bottom_left
    seconds_delay_before_show: 0.0
    seconds_visible: 60

  overlay_player_log_2:
    visible: false

  external_overlay:
    visible: true
    position: top_center
    seconds_visible: 45

# Optional — richer pro-player data on Ctrl+F2
integrations:
  aligulac:
    api_key: ""
```

`position` accepts: `top_left`, `top_right`, `bottom_left`, `bottom_right`, `top_center`,
`bottom_center`, `center`.

---

## Usage

Launch the config editor GUI and run (double-click the `.exe`, or):

```bash
smurfsniper run
```

Run with an explicit config, skipping the GUI:

```bash
smurfsniper run --headless --config config.yaml
```

Validate a config without starting the service:

```bash
smurfsniper validate --config config.yaml --show
```

### Common options

| Option | Description |
|---|---|
| `--config PATH` | Path to the config file (defaults to cwd, then user config dir). |
| `--url URL` | SC2 client API base URL (default `http://localhost:6119`; a trailing `/game` is accepted). |
| `--headless` | Skip the config editor GUI; load the resolved config directly. |
| `--dry-run` | Validate the config and exit without starting the poll loop. |
| `--set KEY=VALUE` | Override a config value inline (repeatable), e.g. `--set me.mmr=4200`. |
| `--version` | Print the version and exit. |

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
smurfsniper run --headless
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
