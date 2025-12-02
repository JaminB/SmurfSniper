from datetime import datetime
from typing import List

from sc_match_briefer.enums import Region, TeamFormat, TeamType


def create_team_legacy_uid(
    queue_type: TeamFormat, team_type: TeamType, region: Region, members: List
) -> str:
    legacy_id = "~".join(
        [
            f"{m.character.realm}.{m.character.battlenetId}.{m.character.realm}"
            for m in members
        ]
    )
    return f"{queue_type.value}-{team_type.value}-{region.value}-{legacy_id}"


def human_friendly_duration(start: datetime, end: datetime | None = None) -> str:
    if end is None:
        end = datetime.utcnow()

    delta_years = end.year - start.year
    delta_months = end.month - start.month
    delta_days = end.day - start.day

    if delta_days < 0:
        delta_months -= 1
    if delta_months < 0:
        delta_years -= 1
        delta_months += 12

    parts = []
    if delta_years > 0:
        parts.append(f"{delta_years} year{'s' if delta_years != 1 else ''}")
    if delta_months > 0:
        parts.append(f"{delta_months} month{'s' if delta_months != 1 else ''}")

    if not parts:
        return "less than a month"

    return " ".join(parts)
