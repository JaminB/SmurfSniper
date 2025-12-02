import asyncio

import httpx
from sounds import two_tone_chime

from sc_match_briefer.analyze import PlayerAnalysis, Team2V2Analysis
from sc_match_briefer.logger import logger
from sc_match_briefer.models.config import Config
from sc_match_briefer.models.player import Player
from sc_match_briefer.overlay_manager import close_all_overlays

CONFIG_FILE = r"C:\Users\jamin\PycharmProjects\sc2-match-briefer\config.yaml"
URL = "http://localhost:6119/game"

config = Config.from_config_file(CONFIG_FILE)


async def poll_games():
    async with httpx.AsyncClient(timeout=10.0) as client:
        previous_state = None
        close_all_overlays()
        while True:
            try:
                r = await client.get(URL)
                r.raise_for_status()
                data = r.json()

                players = data.get("players", [])

                if any(p.get("result") in ["Victory", "Defeat"] for p in players):
                    close_all_overlays()
                    logger.info("Game concluded. Waiting for next lobby...")
                    await asyncio.sleep(5)
                    continue

                if not players:
                    await asyncio.sleep(5)
                    continue

                current_state = tuple(
                    (i, p.get("name"), p.get("race")) for i, p in enumerate(players)
                )

                if current_state == previous_state:
                    await asyncio.sleep(5)
                    continue

                logger.info(f"New game detected: {current_state}")
                close_all_overlays()
                previous_state = current_state

                my_name = config.me.name
                my_team = []
                opp_team = []

                for p in players:
                    name = p.get("name")
                    if name == my_name or name in config.team.members:
                        my_team.append(p)
                    else:
                        opp_team.append(p)

                if not opp_team:
                    logger.info("No opponents found (FFA or error).")
                    await asyncio.sleep(5)
                    continue

                # TODO remove this and support 3v3 and 4v4
                if len(opp_team) > 2:
                    opp_team = [opp_team[0], opp_team[1]]

                if len(opp_team) == 2:
                    logger.info(
                        f"Detected 2v2. Opponents: {[p['name'] for p in opp_team]}"
                    )

                    p1_raw, p2_raw = opp_team

                    opp1 = Player(**p1_raw)
                    opp2 = Player(**p2_raw)

                    ps1 = PlayerAnalysis.from_player_stats(
                        opp1.get_best_match(
                            min_mmr=config.me.mmr - 500,
                            max_mmr=config.me.mmr + 500,
                        ),
                        player=opp1,
                    )

                    ps2 = PlayerAnalysis.from_player_stats(
                        opp2.get_best_match(
                            min_mmr=config.me.mmr - 500,
                            max_mmr=config.me.mmr + 500,
                        ),
                        player=opp2,
                    )

                    # Team HUD
                    team_hud = Team2V2Analysis(ps1, ps2)
                    two_tone_chime()
                    team_hud.show_overlay(duration_seconds=120)

                    await asyncio.sleep(5)
                    continue

                else:
                    opp = opp_team[0]
                    logger.info(f"Looking up opponent {opp['name']} (1v1)…")

                    player_obj = Player(**opp)
                    stats = player_obj.get_best_match(
                        min_mmr=config.me.mmr - 500,
                        max_mmr=config.me.mmr + 500,
                    )
                    analysis = PlayerAnalysis.from_player_stats(
                        stats, player=player_obj
                    )

                    two_tone_chime()
                    analysis.show_overlay(duration_seconds=120)
                    await asyncio.sleep(5)
                    continue

                # ---- Unsupported modes (3v3, 4v4, FFA) ----
                logger.info(
                    f"Unsupported team size: {len(opp_team)} players on enemy team."
                )
                await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"Error while polling: {e}")

            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(poll_games())
