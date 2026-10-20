"""Aligulac (Tastypie) response models."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


def _ref_id(value: Any) -> int | None:
    """Tastypie relations come as nested objects or resource URIs (``/api/v1/player/49/``)."""
    if isinstance(value, dict):
        value = value.get("id")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        m = re.search(r"/(\d+)/?$", value)
        return int(m.group(1)) if m else None
    return None


class AligulacRating(_Model):
    rating: float | None = None
    rating_vp: float | None = None
    rating_vt: float | None = None
    rating_vz: float | None = None
    dev: float | None = None
    decay: int | None = None
    position: int | None = None


class AligulacPlayer(_Model):
    id: int
    tag: str
    name: str | None = None
    country: str | None = None
    race: str | None = None
    birthday: date | None = None
    current_rating: AligulacRating | None = None
    team: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if not isinstance(out.get("current_rating"), dict):
            out["current_rating"] = None
        if not isinstance(out.get("team"), str):
            team = None
            for entry in out.get("current_teams") or []:
                t = entry.get("team") if isinstance(entry, dict) else None
                if isinstance(t, dict) and t.get("name"):
                    team = t["name"]
                    break
            out["team"] = team
        return out

    @property
    def profile_url(self) -> str:
        return f"https://aligulac.com/players/{self.id}/"


class AligulacRatingPoint(_Model):
    """One ``/rating/`` row (a rating period)."""

    id: int | None = None
    period: int | None = None
    rating: float | None = None
    rating_vp: float | None = None
    rating_vt: float | None = None
    rating_vz: float | None = None
    dev: float | None = None
    position: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _period(cls, data: Any) -> Any:
        if isinstance(data, dict) and not isinstance(data.get("period"), int | None):
            data = {**data, "period": _ref_id(data.get("period"))}
        return data


class AligulacMatch(_Model):
    id: int
    date: date
    pla_id: int | None = None
    plb_id: int | None = None
    sca: int | None = None
    scb: int | None = None
    rca: str | None = None
    rcb: str | None = None
    event: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _refs(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        out.setdefault("pla_id", _ref_id(data.get("pla")))
        out.setdefault("plb_id", _ref_id(data.get("plb")))
        ev = data.get("eventobj") or data.get("event")
        out["event"] = ev.get("fullname") if isinstance(ev, dict) else (ev or None)
        return out


class AligulacPrediction(_Model):
    proba: float | None = None
    probb: float | None = None
    bo: int | None = None
