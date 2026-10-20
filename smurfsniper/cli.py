#!/usr/bin/env python3
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import click
import yaml

from smurfsniper import service
from smurfsniper._version import __version__ as VERSION
from smurfsniper.config_paths import resolve_config
from smurfsniper.models.config import Config, Preferences

DEFAULT_URL = "http://localhost:6119"


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise click.ClickException(f"Config file not found: {path}")

    if path.is_dir():
        raise click.ClickException(f"Config path is a directory: {path}")

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def apply_overrides(config: dict[str, Any], overrides: list[str]) -> None:
    """
    Apply overrides of the form key.subkey=value
    NOTE: These apply BEFORE pydantic validation.
    """
    for item in overrides:
        if "=" not in item:
            raise click.ClickException(f"Invalid override '{item}'. Expected key=value")

        key, value = item.split("=", 1)
        parts = key.split(".")

        cursor: dict[str, Any] = config
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})

        v: Any = value
        if value.lower() in {"true", "false"}:
            v = value.lower() == "true"
        else:
            with contextlib.suppress(ValueError):
                v = int(value)

        cursor[parts[-1]] = v


def load_and_validate_config(
    path: Path,
    overrides: list[str],
) -> Config:
    raw = load_config(path)
    apply_overrides(raw, overrides)

    if "preferences" in raw:
        raw["preferences"] = Preferences.from_yaml(raw["preferences"])

    try:
        return Config.model_validate(raw)
    except Exception as e:
        raise click.ClickException(f"Config validation failed: {e}") from e


def masked_dump(config: Config) -> dict[str, Any]:
    """``model_dump`` with secrets masked (``****abcd``)."""
    data = config.model_dump()
    aligulac = ((data.get("integrations") or {}).get("aligulac")) or {}
    key = aligulac.get("api_key")
    if key:
        aligulac["api_key"] = "****" + key[-4:]
    return data


def run_service(
    *,
    url: str,
    config_path: Path,
    config: Config,
    app=None,
) -> None:
    from smurfsniper.logger import logger

    logger.info(f"Config: {config_path}")
    logger.debug(yaml.dump(masked_dump(config), sort_keys=False))
    logger.info(f"Using SC2 client API: {url} (ctrl+c to exit)")

    raise SystemExit(service.main(url=url, config=config, app=app))


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.version_option(VERSION)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """SmurfSniper service runner."""
    # No subcommand (e.g. double-clicking the EXE) -> launch the config GUI + run.
    if ctx.invoked_subcommand is None:
        ctx.invoke(run)


@cli.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(
        exists=False,
        dir_okay=False,
        path_type=Path,
    ),
    default=None,
    help="Path to config file (default: search cwd, then user config dir)",
)
@click.option(
    "--url",
    default=DEFAULT_URL,
    show_default=True,
    help="SC2 client API base URL (a trailing /game is accepted)",
)
@click.option(
    "--headless",
    is_flag=True,
    help="Skip the config editor GUI and load the resolved config directly",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Validate config and exit",
)
@click.option(
    "--set",
    "overrides",
    multiple=True,
    metavar="KEY=VALUE",
    help="Override config values (can be repeated)",
)
def run(
    config_path: Path | None,
    url: str,
    headless: bool,
    dry_run: bool,
    overrides: tuple[str, ...],
) -> None:
    """
    Run the SmurfSniper service.
    """
    from smurfsniper import paths
    from smurfsniper.logger import setup_logging

    paths.ensure_dirs()
    setup_logging("INFO", console=True)
    load_path, write_path = resolve_config(config_path)

    if headless:
        if load_path is None:
            if config_path is not None:
                raise click.ClickException(
                    f"Config file not found: {config_path}; cannot run headless."
                )
            raise click.ClickException("No config file found; cannot run headless.")
        config = load_and_validate_config(load_path, list(overrides))
        if dry_run:
            click.secho("Config is valid", fg="green")
            return
        run_service(url=url, config_path=load_path, config=config)
        return

    # GUI path — create the single QApplication here and reuse it for the loop.
    from PySide6.QtWidgets import QApplication

    from smurfsniper.ui.config_editor import edit_config

    app = QApplication.instance() or QApplication([])

    if load_path is not None:
        prefill = load_and_validate_config(load_path, list(overrides))
    else:
        prefill = Config.defaults()

    edited = edit_config(prefill)
    if edited is None:
        click.echo("Cancelled.")
        return

    edited.write_config_file(write_path)
    click.secho(f"Config saved to {write_path}", fg="green")

    if dry_run:
        click.secho("Config is valid and saved", fg="green")
        return

    run_service(url=url, config_path=write_path, config=edited, app=app)


@cli.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(
        exists=False,
        dir_okay=False,
        path_type=Path,
    ),
    default=None,
    help="Path to config file (default: search cwd, then user config dir)",
)
@click.option(
    "--set",
    "overrides",
    multiple=True,
    metavar="KEY=VALUE",
    help="Override config values (can be repeated)",
)
@click.option(
    "--show",
    is_flag=True,
    help="Print the validated config",
)
def validate(
    config_path: Path | None,
    overrides: tuple[str, ...],
    show: bool,
) -> None:
    """
    Validate the SmurfSniper configuration.
    """
    load_path, _ = resolve_config(config_path)
    if load_path is None:
        if config_path is not None:
            raise click.ClickException(f"Config file not found: {config_path}")
        raise click.ClickException("No config file found.")

    config = load_and_validate_config(
        load_path,
        list(overrides),
    )

    click.secho("Config is valid", fg="green")

    if show:
        click.echo()
        click.echo(yaml.dump(masked_dump(config), sort_keys=False))


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
    """Import every module and build a Qt widget; used by CI to smoke-test the exe."""
    import importlib
    import json
    import os
    import sys

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        import PySide6
        from PySide6.QtWidgets import QApplication, QLabel

        names = _discover_modules()
        for name in names:
            importlib.import_module(name)
        app = QApplication.instance() or QApplication([])
        label = QLabel("self-test")
        label.deleteLater()
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


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
