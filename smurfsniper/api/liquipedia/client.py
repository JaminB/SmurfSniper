"""Liquipedia StarCraft II wiki API client.

Liquipedia's API terms ask for a descriptive, contactable User-Agent, gzip, and about
one request every 2 seconds. ``action=parse`` is far stricter and is never used.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from smurfsniper._version import __version__
from smurfsniper.api.cache import CachePolicy
from smurfsniper.api.liquipedia.models import OpenSearchHit, PageSummary, SearchHit
from smurfsniper.api.params import build_params
from smurfsniper.api.transport import HttpTransport, TokenBucket

BASE_URL = "https://liquipedia.net/starcraft2"
API_PATH = "/api.php"
SERVICE = "liquipedia"
MAX_TITLES = 50

_DAY = CachePolicy(86400)
_TAGS = re.compile(r"<[^>]+>")


def make_limiter() -> TokenBucket:
    return TokenBucket(rate_per_s=0.5, burst=1)


def user_agent(contact: str | None = None) -> str:
    extra = f"; {contact.strip()}" if contact and contact.strip() else ""
    return f"smurfsniper/{__version__} (+https://github.com/JaminB/SmurfSniper{extra})"


def headers(contact: str | None = None) -> dict[str, str]:
    return {"User-Agent": user_agent(contact), "Accept-Encoding": "gzip"}


class LiquipediaClient:
    def __init__(self, transport: HttpTransport):
        self.transport = transport

    def _get(self, params: list[tuple[str, str]], force_refresh: bool) -> Any:
        return self.transport.get_json(API_PATH, params, policy=_DAY, force_refresh=force_refresh)

    def opensearch(
        self, term: str, limit: int = 5, *, force_refresh: bool = False
    ) -> list[OpenSearchHit]:
        params = build_params(action="opensearch", search=term, limit=limit, format="json")
        data = self._get(params, force_refresh)
        if not isinstance(data, list) or len(data) < 4:
            return []
        titles, descs, urls = data[1] or [], data[2] or [], data[3] or []
        return [
            OpenSearchHit(title=t, description=(d or None), url=u)
            for t, d, u in zip(titles, descs + [""] * len(titles), urls, strict=False)
        ]

    def page_summaries(
        self, titles: Sequence[str], *, force_refresh: bool = False
    ) -> dict[str, PageSummary]:
        """Intro extract, portrait and URL per title, batched 50 titles per request.

        Keys are the titles as requested; redirects and normalisation are followed.
        Missing pages are omitted.
        """
        wanted = [t for t in dict.fromkeys(titles) if t]
        out: dict[str, PageSummary] = {}
        for i in range(0, len(wanted), MAX_TITLES):
            batch = wanted[i : i + MAX_TITLES]
            params = build_params(
                action="query",
                prop="extracts|pageprops|info",
                exintro=1,
                explaintext=1,
                exchars=300,
                inprop="url",
                redirects=1,
                format="json",
                titles="|".join(batch),
            )
            data = self._get(params, force_refresh) or {}
            query = data.get("query") or {}
            alias: dict[str, str] = {}
            for step in (query.get("normalized") or []) + (query.get("redirects") or []):
                alias[step.get("from")] = step.get("to")
            by_title: dict[str, PageSummary] = {}
            for page in (query.get("pages") or {}).values():
                if "missing" in page or "invalid" in page or "pageid" not in page:
                    continue
                by_title[page["title"]] = PageSummary(
                    title=page["title"],
                    pageid=page["pageid"],
                    extract=(page.get("extract") or "").strip() or None,
                    image_url=(page.get("pageprops") or {}).get("metaimageurl"),
                    full_url=page.get("fullurl"),
                )
            for t in batch:
                resolved = t
                for _ in range(3):  # normalised -> redirect chain
                    resolved = alias.get(resolved, resolved)
                if resolved in by_title:
                    out[t] = by_title[resolved]
        return out

    def search(self, term: str, limit: int = 5, *, force_refresh: bool = False) -> list[SearchHit]:
        params = build_params(
            action="query", list="search", srsearch=term, srlimit=limit, format="json"
        )
        data = self._get(params, force_refresh) or {}
        hits = (data.get("query") or {}).get("search") or []
        return [
            SearchHit(
                title=h["title"],
                pageid=h.get("pageid"),
                snippet=_TAGS.sub("", h.get("snippet") or "") or None,
            )
            for h in hits
            if h.get("title")
        ]
