# SmurfSniper 🎯

<p align="center">
  <a href="https://buymeacoffee.com/jaminbeckes">
    <img
      src="https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black"
      alt="Buy Me a Coffee"
    />
  </a>
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
- Polls the **local SC2 client API** (`http://localhost:6119/game`) every **5 seconds**.
- Detects new games and the match **format** automatically.
- Supports ranked **1v1**, **2v2**, and team (**3v3 / 4v4**) games.

### Opponent intelligence (SC2Pulse)
- Looks up each opponent's ladder profile, teams, and full MMR history.
- Filters candidate accounts to a **±500 MMR window** around your own (`me.mmr`) for accurate
  matching.
- Resolves race, max league reached, account age, total games, and most-played race.

### MMR & form analysis
- **MMR trend** via linear regression over the last **100 games** (rising / falling).
- **Sparklines** (`▁▂▃▄▅▆▇█`) summarizing recent MMR movement.
- **Win/loss windows** for the last **1 day, 3 days, 7 days, 30 days, and lifetime**.

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
- Detects and surfaces an opponent's **frequent teammates**.

### Cross-network scouting (Ctrl+F2)
On demand, gather a deeper scouting profile on the current opponent(s):
- **Behavioral profile** (from their own ladder history): recent form, current win/loss
  **streak**, **peak activity hours** with a 24-hour activity sparkline, **top maps** with
  W-L records, and **average game length**.
- **External footprint** when the handle is distinctive enough to be worth a public lookup:
  **Aligulac** player page, **Liquipedia** page, **Twitch live** status, the official
  **Battle.net** career link, self-declared **social links**, and candidate handle URLs.
- When an opponent has an external footprint, a distinct **chime** plays and a hint appears on
  the main overlay.

### Configurable overlays
- Frameless, transparent, **always-on-top** widgets that **auto-close** after a set duration.
- Independent settings per overlay type: `1v1`, `2v2`, `team`, two **player-log** overlays, and
  the **external** (Ctrl+F2) overlay.
- Per overlay: `visible`, `orientation` (horizontal / vertical), `position` (8-point screen
  anchor), `seconds_delay_before_show`, and `seconds_visible`.
- Non-blocking rendering on a dedicated Qt UI thread.

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
- Colored console logging plus a rotating `logs/app.log` (10 MB, 14-day retention) via loguru.
- Optional **Aligulac API key** integration for richer pro-player data.
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
Grab the latest `smurfsniper-<version>.exe` from the project's releases / CI artifacts and run it.
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
| `--url URL` | SC2 game API endpoint (default `http://localhost:6119/game`). |
| `--headless` | Skip the config editor GUI; load the resolved config directly. |
| `--dry-run` | Validate the config and exit without starting the poll loop. |
| `--set KEY=VALUE` | Override a config value inline (repeatable), e.g. `--set me.mmr=4200`. |
| `--version` | Print the version and exit. |

---

## License

MIT License.
