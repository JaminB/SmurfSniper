import signal
import sys
import threading

import httpx
import keyboard

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from smurfsniper.api import cross_network, sc2pulse
from smurfsniper.api.sc2pulse import SC2PulseError
from smurfsniper.sounds import footprint_chime, one_tone_chime, two_tone_chime
from smurfsniper.analyze import external_intel
from smurfsniper.analyze.external_intel import ExternalIntel
from smurfsniper.analyze.player_logs import PlayerLogAnalysis
from smurfsniper.analyze.players import Player2v2Analysis, PlayerAnalysis
from smurfsniper.analyze.teams import NoTeamFound, TeamAnalysis
from smurfsniper.enums import TeamFormat
from smurfsniper.logger import logger
from smurfsniper.models.config import Config, OverlayPreferences
from smurfsniper.models.player import Player
from smurfsniper.models.player_log import PlayerLog, init_player_log_db
from smurfsniper.ui.overlay_manager import close_all_overlays


POSTGAME_POSITIONS = [
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
]

class _HintBridge(QObject):
    """Marshals the cross-network hint overlay back onto the Qt thread.

    The scout runs network I/O in a background thread; this bridge (created on
    the Qt thread) lets that worker request the hint overlay via a queued signal
    so the widget is built on the Qt thread.
    """

    show = Signal(object)  # OverlayPreferences

    def __init__(self):
        super().__init__()
        self.show.connect(external_intel.show_hint_overlay)


class GamePoller:
    def __init__(self, url: str, config_path: str):
        init_player_log_db()
        self.url = url
        self.config = Config.from_config_file(config_path)
        self.previous_state = None
        self.mode = TeamFormat._1V1
        self.player_analysis = None
        self.player_2v2_analysis = None
        self.team_analysis = None
        # Raw PlayerStats for the current opponent(s); used by the Ctrl+F2
        # cross-network lookup, which needs identity (name/region/character id).
        self.current_opponents = []
        # Cross-network intel gathered once at game start; reused by Ctrl+F2.
        self.current_intel = []
        # Bridge so the background scout can show its hint on the Qt thread.
        self._hint_bridge = _HintBridge()

    def poll_once(self):
        data = self._fetch_game_state()
        if not data:
            return

        players = data.get("players", [])
        if not players:
            return

        if self._is_game_end(players):
            self._handle_game_end(players)
            return

        if not self._is_new_game(players):
            return

        close_all_overlays()
        self.current_opponents = []
        self.current_intel = []
        logger.info(f"New game detected: {self.previous_state}")

        my_team, opp_team = self._split_teams(players)
        if not opp_team:
            return

        try:
            if len(opp_team) == 1:
                self._handle_1v1(opp_team[0])
            elif len(opp_team) == 2:
                self._handle_2v2(opp_team)
            else:
                self._handle_team_game(opp_team)
        except SC2PulseError as e:
            logger.warning(f"SC2Pulse lookup failed for this game: {e}")

    def _fetch_game_state(self):
        try:
            r = httpx.get(self.url, timeout=5)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"Polling error: {e}")
            return None

    def _is_game_end(self, players) -> bool:
        return any(p.get("result") in {"Victory", "Defeat", "Tie"} for p in players)

    def _is_new_game(self, players) -> bool:
        state = tuple((p.get("name"), p.get("race")) for p in players)
        if state == self.previous_state:
            return False
        self.previous_state = state
        return True

    def _handle_game_end(self, players):
        logger.info("Game ended")
        close_all_overlays()
        self.current_opponents = []
        self.current_intel = []

        me = self.config.me
        teammates = set(self.config.team.members)

        mmr_min = me.mmr - 500
        mmr_max = me.mmr + 500

        for p in players:
            name = p.get("name")
            if name == me.name or name in teammates:
                continue

            player = Player(**p)
            try:
                stats = player.get_player_stats(mmr_min, mmr_max)
            except (SC2PulseError, IndexError) as e:
                logger.warning(f"Could not look up {player.name}: {e}")
                continue

            most_recent = PlayerLog.most_recent()
            log = PlayerLog.from_player_stats(
                stats,
                match_status=p.get("result").lower(),
            )

            if (
                not most_recent
                or most_recent.battlenet_id != stats.members.character.battlenetId
            ):
                logger.info(f"Saving {player.name} to log.")
                log.save()

    def _split_teams(self, players):
        my_team, opp_team = [], []

        for p in players:
            if p.get("name") == self.config.me.name or p.get("name") in self.config.team.members:
                my_team.append(p)
            else:
                opp_team.append(p)

        return my_team, opp_team

    def _handle_1v1(self, opp_raw):
        self.mode = TeamFormat._1V1

        opp = Player(**opp_raw)
        try:
            stats = opp.get_player_stats(
                min_mmr=self.config.me.mmr - 500,
                max_mmr=self.config.me.mmr + 500,
            )
        except (SC2PulseError, IndexError) as e:
            logger.warning(f"Could not look up {opp.name}: {e}")
            return

        self.current_opponents = [stats]
        self._show_opponent_history(
            stats, opp, self.config.preferences.overlay_player_log_1
        )

        self.player_analysis = PlayerAnalysis.from_player_stats(stats, player=opp)

        logger.info(f"Detected 1v1 opponent: {opp.name}")
        two_tone_chime()
        logger.info(self.player_analysis.summary())

        self.player_analysis.show_overlay(
            duration_seconds=self.config.preferences.overlay_1v1.seconds_visible,
            orientation=self.config.preferences.overlay_1v1.orientation,
            position=self.config.preferences.overlay_1v1.position,
            delay_seconds=self.config.preferences.overlay_1v1.seconds_delay_before_show,
        )

        self._scout_and_hint()

    def _scout_and_hint(self):
        """Gather cross-network intel for the current opponents once, cache it
        for Ctrl+F2, and if any opponent has an external footprint play a
        distinct chime and hint that details are available via Ctrl+F2.

        Runs in a background thread: ``ExternalIntel.gather`` performs network
        I/O, and this is invoked from ``poll_once`` on the Qt GUI thread, so the
        work must not block the event loop. The hint overlay is marshalled back
        onto the Qt thread via ``_hint_bridge``.
        """
        opponents = list(self.current_opponents)
        prefs = self.config.preferences.overlay_external
        threading.Thread(
            target=self._do_scout, args=(opponents, prefs), daemon=True
        ).start()

    def _do_scout(self, opponents, prefs):
        intel = []
        for stats in opponents:
            try:
                intel.append(ExternalIntel.gather(stats))
            except Exception as e:  # never break the game flow on a lookup
                logger.warning(f"Cross-network scout failed: {e}")
        self.current_intel = intel

        if any(i.has_external_footprint for i in intel):
            footprint_chime()
            self._hint_bridge.show.emit(prefs)

    def _show_opponent_history(
        self, stats, opp, overlay_preferences: OverlayPreferences
    ):
        try:
            logs = PlayerLogAnalysis.from_battlenet_id(
                stats.members.character.battlenetId
            )
            logs.show_overlay(
                duration_seconds=overlay_preferences.seconds_visible,
                position=overlay_preferences.position,
                orientation=overlay_preferences.orientation,
                delay_seconds=overlay_preferences.seconds_delay_before_show,
            )
        except ValueError:
            logger.info(f"Never played {opp.name} before.")

    def _handle_2v2(self, opp_team):
        self.mode = TeamFormat._2V2

        opp1, opp2 = Player(**opp_team[0]), Player(**opp_team[1])

        try:
            opp1_stats = opp1.get_player_stats(
                self.config.me.mmr - 500, self.config.me.mmr + 500
            )
            opp2_stats = opp2.get_player_stats(
                self.config.me.mmr - 500, self.config.me.mmr + 500
            )
        except (SC2PulseError, IndexError):
            logger.warning("Could not find any records for one or more opponents.")
            return

        self.current_opponents = [opp1_stats, opp2_stats]
        ps1 = PlayerAnalysis.from_player_stats(opp1_stats, player=opp1)
        ps2 = PlayerAnalysis.from_player_stats(opp2_stats, player=opp2)

        logger.info(f"Detected 2v2 opponents: {opp1.name}, {opp2.name}")
        two_tone_chime()

        self._show_opponent_history(
            opp1_stats, opp1, self.config.preferences.overlay_player_log_1
        )
        self._show_opponent_history(
            opp2_stats, opp2, self.config.preferences.overlay_player_log_2
        )

        self.player_2v2_analysis = Player2v2Analysis(ps1, ps2)
        self.player_2v2_analysis.show_overlay(
            duration_seconds=self.config.preferences.overlay_2v2.seconds_visible,
            orientation=self.config.preferences.overlay_2v2.orientation,
            position=self.config.preferences.overlay_2v2.position,
            delay_seconds=self.config.preferences.overlay_2v2.seconds_delay_before_show,
        )

        try:
            self.team_analysis = TeamAnalysis.from_players_stats(
                player_stats=[opp1_stats, opp2_stats]
            )
            self.team_analysis.show_overlay(
                duration_seconds=self.config.preferences.overlay_2v2.seconds_visible,
                orientation=self.config.preferences.overlay_team.orientation,
                position=self.config.preferences.overlay_team.position,
                delay_seconds=self.config.preferences.overlay_team.seconds_delay_before_show,
            )
        except NoTeamFound:
            logger.warning(f"No team found for {opp1.name}, {opp2.name}")

        self._scout_and_hint()

    def _handle_team_game(self, opp_team):
        self.mode = TeamFormat._3V3 if len(opp_team) == 3 else TeamFormat._4V4

        try:
            opp_stats = [
                Player(**p).get_player_stats(
                    min_mmr=self.config.me.mmr - 500,
                    max_mmr=self.config.me.mmr,
                )
                for p in opp_team
            ]
        except (SC2PulseError, IndexError):
            logger.warning("Could not find any records for one or more opponents.")
            return

        self.current_opponents = list(opp_stats)
        try:
            self.team_analysis = TeamAnalysis.from_players_stats(player_stats=opp_stats)
            self.team_analysis.show_overlay(
                duration_seconds=self.config.preferences.overlay_2v2.seconds_visible,
                orientation=self.config.preferences.overlay_team.orientation,
                position=self.config.preferences.overlay_team.position,
                delay_seconds=self.config.preferences.overlay_2v2.seconds_delay_before_show,
            )
        except NoTeamFound:
            logger.warning(f"No team found for {opp_stats}")

        self._scout_and_hint()


class _F2Bridge(QObject):
    """Marshals Ctrl+F2 results from the keyboard thread onto the Qt thread.

    The ``keyboard`` callback runs in the library's listener thread, but Qt
    widgets must be built on the Qt thread. The callback does its network work
    in its own thread, then emits ``ready`` (a queued cross-thread connection),
    so ``_render`` builds the overlay safely on the Qt thread.
    """

    ready = Signal(object, object)  # (list[ExternalIntel], OverlayPreferences)

    def __init__(self):
        super().__init__()
        self.ready.connect(self._render)

    def _render(self, intels, prefs):
        external_intel.render_overlay(intels, prefs)


def main(url:str, config_file_path: str):
    app = QApplication([])
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    poller = GamePoller(url, config_file_path)

    integrations = poller.config.integrations
    if integrations and integrations.aligulac:
        cross_network.set_aligulac_api_key(integrations.aligulac.api_key)

    bridge = _F2Bridge()
    f2_lock = threading.Lock()

    def on_ctrl_f1():
        one_tone_chime()
        poller.previous_state = "{}"

    def on_ctrl_f2():
        # Skip if a previous F2 lookup is still in flight (guards against spam).
        if not f2_lock.acquire(blocking=False):
            return
        try:
            one_tone_chime()
            prefs = poller.config.preferences.overlay_external

            # Reuse intel already gathered at game start; only fetch on demand
            # if a game is active but the scout has not run yet.
            intels = list(poller.current_intel)
            if not intels:
                opponents = list(poller.current_opponents)
                if not opponents:
                    logger.info("Ctrl+F2: no current opponent to look up.")
                    return
                for stats in opponents:
                    try:
                        intels.append(ExternalIntel.gather(stats))
                    except Exception as exc:  # never let the hotkey thread die
                        logger.warning(f"Ctrl+F2 lookup failed: {exc}")

            if intels:
                bridge.ready.emit(intels, prefs)
        finally:
            f2_lock.release()

    keyboard.add_hotkey("ctrl+f1", on_ctrl_f1)
    keyboard.add_hotkey("ctrl+f2", on_ctrl_f2)

    timer = QTimer()
    timer.timeout.connect(poller.poll_once)
    timer.start(5000)

    exit_code = app.exec()

    keyboard.unhook_all()
    sc2pulse.close()
    cross_network.close()
    sys.exit(exit_code)
