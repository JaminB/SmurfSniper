"""Config v2: typed settings, v1 migration, atomic save and dotted-key overrides."""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from smurfsniper import paths
from smurfsniper.logger import logger

QUEUE_1V1 = 201
BACKUP_NAME = "config.v1.bak.yaml"


class ConfigError(ValueError):
    """The config file or an override could not be read or validated."""


class Anchor(StrEnum):
    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    CENTER_LEFT = "center_left"
    CENTER = "center"
    CENTER_RIGHT = "center_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)


class Placement(_Model):
    anchor: Anchor
    offset_x: int = 0  # px at scale 1.0, positive = right
    offset_y: int = 0  # px at scale 1.0, positive = down


class AccountConfig(_Model):
    character_id: int | None = None
    toon_handle: str | None = None
    name: str | None = None  # base name (no #discriminator), as shown in game
    region: Literal["US", "EU", "KR", "CN"] | None = None
    auto_detect: bool = True
    mmr_by_queue: dict[int, int] = Field(default_factory=dict)
    mmr_updated_at: datetime | None = None
    mmr_override: int | None = None
    teammates: list[str] = Field(default_factory=list)

    def mmr_for(self, queue: int) -> int | None:
        """Manual override, else the queue's rating, else the 1v1 rating, else None."""
        if self.mmr_override is not None:
            return self.mmr_override
        if queue in self.mmr_by_queue:
            return self.mmr_by_queue[queue]
        return self.mmr_by_queue.get(QUEUE_1V1)


class SurfaceConfig(_Model):
    enabled: bool = True
    placement: Placement


class CardConfig(SurfaceConfig):
    auto_hide_seconds: int = 45  # 0 = stay until the game ends


class ToastConfig(SurfaceConfig):
    seconds: float = 6.0
    max_visible: int = 4


class HintConfig(SurfaceConfig):
    seconds: float = 6.0


class PanelConfig(_Model):
    placement: Placement


def _card() -> CardConfig:
    return CardConfig(placement=Placement(anchor=Anchor.TOP_CENTER, offset_y=72))


def _toasts() -> ToastConfig:
    return ToastConfig(placement=Placement(anchor=Anchor.TOP_RIGHT, offset_y=120))


def _hint() -> HintConfig:
    return HintConfig(placement=Placement(anchor=Anchor.BOTTOM_CENTER, offset_y=-260))


def _panels() -> PanelConfig:
    return PanelConfig(placement=Placement(anchor=Anchor.CENTER_RIGHT, offset_x=-24))


class OverlayConfig(_Model):
    opacity: float = Field(0.70, ge=0.40, le=1.0)
    scale: float = Field(1.0, ge=0.75, le=1.5)
    screen: int | None = None  # QScreen index; None = primary
    card: CardConfig = Field(default_factory=_card)
    toasts: ToastConfig = Field(default_factory=_toasts)
    hint: HintConfig = Field(default_factory=_hint)
    panels: PanelConfig = Field(default_factory=_panels)
    show_in_replays: bool = False


class HotkeyConfig(_Model):
    opponent_card: str = "ctrl+shift+1"
    intel: str = "ctrl+shift+2"
    session: str = "ctrl+shift+3"
    rivals: str = "ctrl+shift+4"
    redetect: str = "ctrl+shift+r"
    hide_all: str = "ctrl+shift+`"
    enabled: bool = True


class IntegrationsConfig(_Model):
    aligulac_api_key: SecretStr | None = None
    liquipedia_enabled: bool = True
    liquipedia_contact: str | None = None


class AdvancedConfig(_Model):
    sc2_client_url: str = "http://localhost:6119"
    ui_poll_ms: int = Field(1500, ge=500, le=10000)
    mmr_window: int = Field(500, ge=100, le=2000)
    sounds_enabled: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING"] = "INFO"
    disk_cache: bool = True


class Config(_Model):
    version: Literal[2] = 2
    account: AccountConfig = Field(default_factory=AccountConfig)
    overlays: OverlayConfig = Field(default_factory=OverlayConfig)
    hotkeys: HotkeyConfig = Field(default_factory=HotkeyConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    advanced: AdvancedConfig = Field(default_factory=AdvancedConfig)

    @property
    def aligulac_key(self) -> str:
        key = self.integrations.aligulac_api_key
        return key.get_secret_value().strip() if key else ""

    def replace_with(self, other: Config) -> None:
        """Copy every section from ``other`` in place so shared references stay valid."""
        for name in type(self).model_fields:
            setattr(self, name, getattr(other, name))


# ------------------------------------------------------------------- helpers
def mask_secret(value: str | None) -> str | None:
    """``abcdef1234`` -> ``****1234``. Never reveals more than the last 4 characters."""
    if not value:
        return None
    return "****" + value[-4:]


def masked_dump(config: Config) -> dict[str, Any]:
    """JSON-friendly dump with the Aligulac key masked."""
    data = config.model_dump(mode="json")
    data["integrations"]["aligulac_api_key"] = mask_secret(config.aligulac_key)
    return data


def config_path() -> Path:
    return paths.config_dir() / "config.yaml"


# ----------------------------------------------------------------- migration
def _anchor(value: Any) -> Anchor | None:
    try:
        return Anchor(str(value))
    except ValueError:
        return None


def migrate_v1(raw: dict[str, Any]) -> Config:
    """Build a v2 config from a v1 mapping (``me``/``team``/``preferences``)."""
    data: dict[str, Any] = {"version": 2}
    account: dict[str, Any] = {}
    me = raw.get("me") or {}
    if me.get("name"):
        account["name"] = str(me["name"]).split("#")[0].strip()
    if isinstance(me.get("mmr"), int):
        account["mmr_by_queue"] = {QUEUE_1V1: me["mmr"]}
    members = (raw.get("team") or {}).get("members")
    if members:
        account["teammates"] = [str(m) for m in members]
    data["account"] = account

    prefs = raw.get("preferences") or {}
    card: dict[str, Any] = {}
    one = prefs.get("1v1_overlay") or {}
    anchor = _anchor(one.get("position"))
    if anchor is not None:
        card["placement"] = {"anchor": anchor.value}
    if isinstance(one.get("seconds_visible"), int):
        card["auto_hide_seconds"] = one["seconds_visible"]
    if "visible" in one:
        card["enabled"] = bool(one["visible"])
    if card:
        card.setdefault("placement", _card().placement.model_dump())
        data["overlays"] = {"card": card}
    for key in (
        "2v2_overlay",
        "team_overlay",
        "overlay_player_log_1",
        "overlay_player_log_2",
        "external_overlay",
    ):
        if key in prefs:
            logger.info(f"Config migration: dropping legacy preference '{key}'")

    key = (((raw.get("integrations") or {}).get("aligulac")) or {}).get("api_key")
    if key:
        data["integrations"] = {"aligulac_api_key": str(key)}
    if "aws_bedrock" in (raw.get("integrations") or {}):
        logger.info("Config migration: dropping 'integrations.aws_bedrock' (never re-written)")
    return Config.model_validate(data)


def is_v1(raw: Any) -> bool:
    return isinstance(raw, dict) and "version" not in raw and ("me" in raw or "preferences" in raw)


# ------------------------------------------------------------------ load/save
def load_config(path: Path | None = None, *, write_migration: bool = True) -> tuple[Config, Path]:
    """Load ``path`` (default: the user config file).

    A missing file yields defaults (not written until the first save). A v1 file is
    migrated; when ``write_migration`` is set the original is copied to
    ``config.v1.bak.yaml`` and the v2 file is written in its place.
    """
    path = Path(path) if path is not None else config_path()
    if path.is_dir():
        raise ConfigError(f"Config path is a directory: {path}")
    if not path.exists():
        return Config(), path
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"Could not read {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"Config file {path} must contain a mapping")
    try:
        if is_v1(raw):
            config = migrate_v1(raw)
            logger.info(f"Migrated v1 config {path} to v2")
            if write_migration:
                shutil.copyfile(path, path.with_name(BACKUP_NAME))
                save_config(config, path)
            return config, path
        return Config.model_validate(raw), path
    except ValidationError as e:
        raise ConfigError(f"Config validation failed: {e}") from e


def save_config(config: Config, path: Path) -> None:
    """Atomically write ``config`` as YAML (tmp file + ``os.replace``)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump(mode="json")
    key = config.aligulac_key
    data["integrations"]["aligulac_api_key"] = key or None
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    os.replace(tmp, path)


# ------------------------------------------------------------------ overrides
def _parse_value(text: str) -> Any:
    low = text.strip().lower()
    if low in {"true", "false"}:
        return low == "true"
    if low in {"null", "none", "~"}:
        return None
    for conv in (int, float):
        try:
            return conv(text)
        except ValueError:
            continue
    return text


def apply_overrides(config: Config, overrides: Sequence[str]) -> Config:
    """Apply ``dotted.key=value`` overrides and re-validate. The input is not mutated."""
    data = config.model_dump()
    for item in overrides:
        if "=" not in item:
            raise ConfigError(f"Invalid override '{item}'. Expected key=value")
        key, value = item.split("=", 1)
        parts = key.strip().split(".")
        cursor: Any = data
        for part in parts[:-1]:
            nxt = cursor.get(part) if isinstance(cursor, dict) else None
            if nxt is None and isinstance(cursor, dict) and part in cursor:
                nxt = cursor[part] = {}
            if not isinstance(nxt, dict):
                raise ConfigError(f"Unknown config key '{key}'")
            cursor = nxt
        leaf = parts[-1]
        if leaf not in cursor and parts[-2:-1] != ["mmr_by_queue"]:
            raise ConfigError(f"Unknown config key '{key}'")
        if parts[-2:-1] == ["mmr_by_queue"]:
            leaf = int(leaf)  # type: ignore[assignment]
        cursor[leaf] = _parse_value(value)
    try:
        return Config.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"Config validation failed: {e}") from e
