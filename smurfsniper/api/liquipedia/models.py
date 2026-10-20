"""Liquipedia MediaWiki API models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class OpenSearchHit(_Model):
    title: str
    description: str | None = None
    url: str


class PageSummary(_Model):
    title: str
    pageid: int
    extract: str | None = None
    image_url: str | None = None
    full_url: str | None = None


class SearchHit(_Model):
    title: str
    pageid: int | None = None
    snippet: str | None = None
