"""Liquipedia wiki API client package."""

from smurfsniper.api.liquipedia.client import BASE_URL, LiquipediaClient, headers, make_limiter
from smurfsniper.api.liquipedia.models import OpenSearchHit, PageSummary, SearchHit

__all__ = [
    "BASE_URL",
    "LiquipediaClient",
    "OpenSearchHit",
    "PageSummary",
    "SearchHit",
    "headers",
    "make_limiter",
]
