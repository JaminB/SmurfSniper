#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml

from smurfsniper._version import __version__ as VERSION
from smurfsniper.models.config import (
    Config,
    ConfigError,
    apply_overrides,
    load_config,
    masked_dump,
)

CONFIG_OPTION = click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
    default=None,
    help="Path to config file (default: the user config directory)",
)
SET_OPTION = click.option(
    "--set",
    "overrides",
    multiple=True,
    metavar="KEY=VALUE",
    help="Override a config value in memory, e.g. overlays.opacity=0.8 (repeatable)",
)


def load_and_override(
    config_path: Path | None, overrides: tuple[str, ...], *, write_migration: bool = True
) -> tuple[Config, Path]:
    try:
        config, path = load_config(config_path, write_migration=write_migration)
        return apply_overrides(config, overrides), path
    except ConfigError as e:
        raise click.ClickException(str(e)) from e


def dump_text(config: Config) -> str:
    return yaml.dump(masked_dump(config), sort_keys=False, allow_unicode=True)


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.version_option(VERSION, "-V", "--version")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """SmurfSniper: smurf-spotting overlay for StarCraft II."""
    # No subcommand (e.g. double-clicking the exe) runs the tray app.
    if ctx.invoked_subcommand is None:
        ctx.invoke(run)


@cli.command()
@CONFIG_OPTION
@click.option("--url", default=None, help="SC2 client API base URL (a trailing /game is accepted)")
@click.option("--no-tray", is_flag=True, help="Run without a tray icon; quit with Ctrl+C")
@click.option("--dry-run", is_flag=True, help="Validate the config, print it and exit")
@SET_OPTION
def run(
    config_path: Path | None,
    url: str | None,
    no_tray: bool,
    dry_run: bool,
    overrides: tuple[str, ...],
) -> None:
    """Run SmurfSniper (tray app by default)."""
    from smurfsniper import paths
    from smurfsniper.logger import logger, setup_logging

    extra = (f"advanced.sc2_client_url={url.rstrip('/').removesuffix('/game')}",) if url else ()
    config, path = load_and_override(config_path, (*overrides, *extra), write_migration=not dry_run)
    if dry_run:
        click.echo(dump_text(config))
        click.secho("Config is valid", fg="green")
        return

    paths.ensure_dirs()
    setup_logging(config.advanced.log_level, console=True)
    logger.info(f"SmurfSniper {VERSION}; config: {path}")
    logger.debug(dump_text(config))

    from smurfsniper.app.application import SmurfSniperApp

    app = SmurfSniperApp(config, path, tray=not no_tray)
    raise SystemExit(app.run())


@cli.command()
@CONFIG_OPTION
@SET_OPTION
@click.option("--show", is_flag=True, help="Print the validated config (secrets masked)")
def validate(config_path: Path | None, overrides: tuple[str, ...], show: bool) -> None:
    """Validate the SmurfSniper configuration."""
    config, _ = load_and_override(config_path, overrides, write_migration=False)
    click.secho("Config is valid", fg="green")
    if show:
        click.echo()
        click.echo(dump_text(config))


@cli.group()
def cache() -> None:
    """Inspect or clear the on-disk API response cache."""


def _open_disk_cache():
    from smurfsniper import paths
    from smurfsniper.api.cache import DiskCache

    path = paths.http_cache_path()
    if not path.exists():
        return None
    return DiskCache(path)


@cache.command("stats")
def cache_stats() -> None:
    """Show how many responses are cached."""
    disk = _open_disk_cache()
    if disk is None:
        click.echo("Cache: 0 entries · 0 KB")
        return
    try:
        entries, size = disk.stats()
    finally:
        disk.close()
    from smurfsniper.ui.settings.tab_advanced import format_bytes

    click.echo(f"Cache: {entries:,} entries · {format_bytes(size)}")


@cache.command("clear")
def cache_clear() -> None:
    """Delete every cached response."""
    disk = _open_disk_cache()
    if disk is None:
        click.echo("Cache is already empty.")
        return
    try:
        disk.clear()
    finally:
        disk.close()
    click.secho("Cache cleared", fg="green")


def _discover_modules() -> list[str]:
    """Every importable module name under the smurfsniper package.

    Falls back to the static list in ``_modules.py`` when the package is frozen and
    ``pkgutil`` cannot see the PyInstaller-archived modules.
    """
    import pkgutil

    import smurfsniper

    names = sorted(
        m.name for m in pkgutil.walk_packages(smurfsniper.__path__, prefix="smurfsniper.")
    )
    if not names:
        from smurfsniper._modules import MODULES

        names = list(MODULES)
    return names


@cli.command("self-test", hidden=True)
@click.option(
    "--output",
    "output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Where to write the JSON result",
)
def self_test(output: Path) -> None:
    """Import every module, load assets and build Qt widgets; CI smoke-tests the exe."""
    import importlib
    import json
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        import PySide6
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication

        names = _discover_modules()
        for name in names:
            importlib.import_module(name)
        app = QApplication.instance() or QApplication([])
        from smurfsniper.assets import asset_path

        for asset in ("logo.ico", "logo.png", "tray.png"):
            if not asset_path(asset).is_file():
                raise FileNotFoundError(f"missing asset {asset}")
        if QIcon(str(asset_path("tray.png"))).isNull():
            raise RuntimeError("tray.png did not load")
        from smurfsniper.ui.settings import SettingsWindow

        window = SettingsWindow(Config())
        window.deleteLater()
        _self_test_hud()
        del app
        result: dict[str, Any] = {
            "version": VERSION,
            "modules": len(names),
            "qt": PySide6.__version__,
            "ok": True,
        }
        code = 0
    except Exception as e:  # report any failure to CI
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        code = 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result), encoding="utf-8")
    sys.exit(code)


def _self_test_hud() -> None:
    """Build and render a full opponent card and the intel, session and rivals panels."""
    from PySide6.QtGui import QImage

    from smurfsniper.ui import preview_data as pd
    from smurfsniper.ui.overlay import OpponentCard, Panel, set_animations_enabled
    from smurfsniper.ui.panels import rivals, session
    from smurfsniper.ui.panels.intel import build_intel_body
    from smurfsniper.ui.tokens import TokenContext

    set_animations_enabled(False)
    try:
        tk, ov = TokenContext(), Config().overlays
        card = OpponentCard(tk, ov.card.placement, now=lambda: pd.NOW)
        prof = pd.smurf_profile()
        card.start(1, [prof.seed], my_race="ZERG")
        for u in pd.updates_for(1, 0, prof):
            card.apply(u)
        panel = Panel("Scouting intel", "Ctrl+Shift+2", tk, ov.panels.placement)
        panel.set_body(build_intel_body([pd.intel_profile()], tk) or [])
        extra = []
        for title, key, body in (
            ("Session", "Ctrl+Shift+3", session.build(pd.session_snapshot(), tk)),
            ("Rivals", "Ctrl+Shift+4", rivals.build(pd.rivals_summary(), tk, now=pd.NOW)),
        ):
            p = Panel(title, key, tk, ov.panels.placement)
            p.set_body(body or [])
            extra.append(p)
        for w in (card, panel, *extra):
            w.reveal()
            img = QImage(w.size(), QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(0)
            w.render(img)
            w.hide_now()
        if card.row_count() < 6:
            raise RuntimeError(f"opponent card built {card.row_count()} rows, expected 6")
    finally:
        set_animations_enabled(True)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
