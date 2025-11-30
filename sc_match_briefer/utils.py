from typing import List
from sc_match_briefer.enums import Region, TeamFormat, TeamType


def create_team_legacy_uid(
    queue_type: TeamFormat,
    team_type: TeamType,
    region: Region,
    members: List
) -> str:
    legacy_id = "~".join([
        f"{m.character.realm}.{m.character.battlenetId}.{m.character.realm}"
        for m in members
    ])
    return f"{queue_type.value}-{team_type.value}-{region.value}-{legacy_id}"
