import keyboard
import requests
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from sounds import one_tone_chime, two_tone_chime

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

    # ---------------- Public API ----------------

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
        logger.info(f"New game detected: {self.previous_state}")

        my_team, opp_team = self._split_teams(players)
        if not opp_team:
            return

        if len(opp_team) == 1:
            self._handle_1v1(opp_team[0])
        elif len(opp_team) == 2:
            self._handle_2v2(opp_team)
        else:
            self._handle_team_game(opp_team)

    def _fetch_game_state(self):
        try:
            r = requests.get(self.url, timeout=5)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"Polling error: {e}")
            return None

    def _is_game_end(self, players) -> bool:
        results = {"Victory", "Defeat", "Tie"}
        return any(p.get("result") in results for p in players)

    def _is_new_game(self, players) -> bool:
        state = tuple((p.get("name"), p.get("race")) for p in players)
        if state == self.previous_state:
            return False
        self.previous_state = state
        return True

    def _handle_game_end(self, players):
        logger.info("Game ended")
        close_all_overlays()

        me = self.config.me
        teammates = set(self.config.team.members)

        mmr_min = me.mmr - 500
        mmr_max = me.mmr + 500

        for p in players:
            name = p.get("name")
            if name == me or name in teammates:
                continue

            player = Player(**p)
            stats = player.get_player_stats(mmr_min, mmr_max)

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
        my_team = []
        opp_team = []

        for p in players:
            if (
                p.get("name") == self.config.me
                or p.get("name") in self.config.team.members
            ):
                my_team.append(p)
            else:
                opp_team.append(p)

        return my_team, opp_team

    def _handle_1v1(self, opp_raw):
        self.mode = TeamFormat._1V1

        opp = Player(**opp_raw)
        stats = opp.get_player_stats(
            min_mmr=self.config.me.mmr - 500,
            max_mmr=self.config.me.mmr + 500,
        )

        self._show_opponent_history(
            stats, opp, self.config.preferences.overlay_player_log_1
        )

        self.player_analysis = PlayerAnalysis.from_player_stats(
            stats,
            player=opp,
        )

        logger.info(f"Detected 1v1 opponent: {opp.name}")
        two_tone_chime()
        logger.info(self.player_analysis.summary())

        self.player_analysis.show_overlay(
            duration_seconds=self.config.preferences.overlay_1v1.seconds_visible,
            orientation=self.config.preferences.overlay_1v1.orientation,
            position=self.config.preferences.overlay_1v1.position,
            delay_seconds=self.config.preferences.overlay_1v1.seconds_delay_before_show,
        )

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

        opp1 = Player(**opp_team[0])
        opp2 = Player(**opp_team[1])

        opp1_stats = opp1.get_player_stats(
            self.config.me.mmr - 500, self.config.me.mmr + 500
        )
        opp2_stats = opp2.get_player_stats(
            self.config.me.mmr - 500, self.config.me.mmr + 500
        )

        ps1 = PlayerAnalysis.from_player_stats(opp1_stats, player=opp1)
        ps2 = PlayerAnalysis.from_player_stats(opp2_stats, player=opp2)

        logger.info(f"Detected 2v2 opponents: {opp1.name}, {opp2.name}")
        two_tone_chime()

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

    def _handle_team_game(self, opp_team):
        self.mode = TeamFormat._3V3 if len(opp_team) == 3 else TeamFormat._4V4

        opp_stats = [
            Player(**p).get_player_stats(
                min_mmr=self.config.me.mmr - 500,
                max_mmr=self.config.me.mmr,
            )
            for p in opp_team
        ]

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


CONFIG_FILE = r"C:\Users\jamin\PycharmProjects\smurfsniper\config.yaml"
URL = "http://localhost:6119/game"


if __name__ == "__main__":
    app = QApplication([])

    poller = GamePoller(URL, CONFIG_FILE)

    def on_ctrl_f1():
        one_tone_chime()
        poller.previous_state = "{}"

    keyboard.add_hotkey("ctrl+f1", on_ctrl_f1)

    timer = QTimer()
    timer.timeout.connect(poller.poll_once)
    timer.start(5000)

    app.exec()
