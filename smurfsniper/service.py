import keyboard
import requests
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from sounds import one_tone_chime, two_tone_chime

from smurfsniper.analyze import PlayerAnalysis, Team2V2Analysis
from smurfsniper.enums import TeamFormat
from smurfsniper.logger import logger
from smurfsniper.models.config import Config
from smurfsniper.models.player import Player
from smurfsniper.ui.overlay_manager import close_all_overlays


class GamePoller:
    def __init__(self, url: str, config_path: str):
        self.url = url
        self.config = Config.from_config_file(config_path)
        self.previous_state = None
        self.mode = TeamFormat._1V1
        self.player_analysis = None
        self.team_2v2_analysis = None

    def poll_once(self):
        try:
            r = requests.get(self.url, timeout=5)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.error(f"Polling error: {e}")
            return

        players = data.get("players", [])
        if not players:
            return

        if any(p.get("result") in ["Victory", "Defeat"] for p in players):
            close_all_overlays()
            logger.info("Game ended, waiting for next lobby…")
            return

        current_state = tuple((p.get("name"), p.get("race")) for p in players)

        if current_state == self.previous_state:
            return

        self.previous_state = current_state
        close_all_overlays()
        logger.info(f"New game detected: {current_state}")

        my_name = self.config.me.name
        my_team = []
        opp_team = []

        for p in players:
            if p.get("name") == my_name or p.get("name") in self.config.team.members:
                my_team.append(p)
            else:
                opp_team.append(p)

        if not opp_team:
            return

        # Only support 1v1 and 2v2 for now
        if len(opp_team) > 2:
            opp_team = opp_team[:2]

        # ---- 2v2 ----
        if len(opp_team) == 2:
            self.mode = TeamFormat._2V2
            p1_raw, p2_raw = opp_team

            opp1 = Player(**p1_raw)
            opp2 = Player(**p2_raw)

            ps1 = PlayerAnalysis.from_player_stats(
                opp1.get_best_match(
                    min_mmr=self.config.me.mmr - 500, max_mmr=self.config.me.mmr + 500
                ),
                player=opp1,
            )
            ps2 = PlayerAnalysis.from_player_stats(
                opp2.get_best_match(
                    min_mmr=self.config.me.mmr - 500, max_mmr=self.config.me.mmr + 500
                ),
                player=opp2,
            )

            logger.info(f"Detected 2v2 opponents: {opp1.name}, {opp2.name}")
            two_tone_chime()

            hud = Team2V2Analysis(ps1, ps2)
            self.team_2v2_analysis = hud
            hud.show_overlay(
                duration_seconds=self.config.preferences.overlay_2v2.seconds_visible
            )
            return

        # ---- 1v1 ----
        opp_raw = opp_team[0]
        opp_obj = Player(**opp_raw)

        stats = opp_obj.get_best_match(
            min_mmr=self.config.me.mmr - 500,
            max_mmr=self.config.me.mmr + 500,
        )
        analysis = PlayerAnalysis.from_player_stats(stats, player=opp_obj)
        self.player_analysis = analysis
        logger.info(f"Detected 1v1 opponent: {opp_obj.name}")
        two_tone_chime()

        analysis.show_overlay(
            duration_seconds=self.config.preferences.overlay_1v1.seconds_visible
        )


CONFIG_FILE = r"C:\Users\jamin\PycharmProjects\smurfsniper\config.yaml"
URL = "http://localhost:6119/game"


if __name__ == "__main__":
    app = QApplication([])

    poller = GamePoller(URL, CONFIG_FILE)

    # FIXED: real function instead of lambda
    def on_ctrl_f1():
        one_tone_chime()
        poller.previous_state = "{}"

    keyboard.add_hotkey("ctrl+f1", on_ctrl_f1)

    timer = QTimer()
    timer.timeout.connect(poller.poll_once)
    timer.start(5000)

    app.exec()
