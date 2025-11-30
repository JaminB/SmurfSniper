import asyncio
import httpx

from sc_match_briefer.logger import logger
from sc_match_briefer.models.player import print_player_summary
from sc_match_briefer.models.player import Player
from sc_match_briefer.models.config import Config



CONFIG_FILE = r"/Users/jamin.becker/PycharmProjects/sc2-match-briefer/config.yaml"
URL = "http://localhost:6119/game"

config = Config.from_config_file(CONFIG_FILE)


async def poll_games():
    async with httpx.AsyncClient(timeout=5.0) as client:
        while True:
            try:
                r = await client.get(URL)
                r.raise_for_status()
                data = r.json()
                players = data["players"]
                if len(players) == 2:
                    for player in players:
                        player = Player(**player)
                        if player.name == config.me.name:
                            continue
                        if player.name in config.team.members:
                            continue
                        logger.info(f"Looking up {player.name}.")
                        player_stats = player.get_best_match(min_mmr=config.me.mmr - 500, max_mmr=config.me.mmr + 500)
                        print_player_summary(player_name = player.name, player_stats = player_stats, history = player_stats.match_history)
            except Exception as e:
                print("Error:", e)

            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(poll_games())
