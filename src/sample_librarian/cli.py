from __future__ import annotations

from pathlib import Path

import click

from sample_librarian.classify.classifier import load_taxonomy
from sample_librarian.config import ConfigError, load_settings
from sample_librarian.db import repository
from sample_librarian.pipeline.initial_sweep import run_dry_run_sweep

DEFAULT_CONFIG_PATH = Path("config/settings.toml")
DEFAULT_TAXONOMY_PATH = Path("config/taxonomy.yaml")

_config_option = click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=DEFAULT_CONFIG_PATH,
    show_default=True,
    help="Path to settings.toml (copy config/settings.example.toml to get started).",
)


@click.group()
def main() -> None:
    """sample-librarian: organize and browse a scattered sample library."""


@main.command("init")
@_config_option
def init_cmd(config_path: Path) -> None:
    """Create the library_root directory structure (vendor/, inbox/, unsorted/, db/, logs/)."""
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    for d in (settings.vendor_dir, settings.inbox_dir, settings.unsorted_dir, settings.db_path.parent, settings.logs_dir):
        d.mkdir(parents=True, exist_ok=True)
        click.echo(f"ok  {d}")

    with repository.open_db(settings.db_path):
        pass  # just ensures schema is created
    click.echo(f"ok  {settings.db_path} (schema ready)")


@main.command("scan")
@_config_option
@click.option(
    "--taxonomy",
    "taxonomy_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=DEFAULT_TAXONOMY_PATH,
    show_default=True,
)
@click.option("--limit", type=int, default=None, help="Only show the first N planned actions.")
def scan_cmd(config_path: Path, taxonomy_path: Path, limit: int | None) -> None:
    """Dry-run a full sweep of scan_roots and report what it would do.

    This never touches your files -- real move/symlink execution (--apply)
    isn't implemented yet.
    """
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    taxonomy_rules = load_taxonomy(taxonomy_path)

    with repository.open_db(settings.db_path) as conn:
        report = run_dry_run_sweep(settings, taxonomy_rules, conn)

    click.echo(f"Scanned {report.files_scanned} audio file(s)")
    click.echo(f"  vendor (would symlink only): {report.vendor_count}")
    click.echo(f"  orphan (would move + stub-symlink): {report.orphan_count}")
    if report.errors:
        click.echo(f"  errors: {len(report.errors)}")

    shown = report.actions[:limit] if limit else report.actions
    for action in shown:
        tags = ",".join(action.tags) if action.tags else "-"
        bpm = f"{action.bpm:.0f}bpm[{action.bpm_source}]" if action.bpm else "-"
        key = f"{action.musical_key}[{action.key_source}]" if action.musical_key else "-"
        click.echo(
            f"  [{action.bucket:6}] {action.source_path} -> {action.target_path}\n"
            f"           type={action.sample_type or '-'} tags={tags} bpm={bpm} key={key}"
        )

    for path, error in report.errors:
        click.echo(f"  ERROR {path}: {error}", err=True)


@main.command("stats")
@_config_option
def stats_cmd(config_path: Path) -> None:
    """Show counts from the library database (empty until a real --apply run exists)."""
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    with repository.open_db(settings.db_path) as conn:
        total = repository.count_samples(conn)
        by_bucket = repository.count_by_bucket(conn)
        by_type = repository.count_by_type(conn)

    click.echo(f"Total samples in library: {total}")
    for bucket, n in by_bucket.items():
        click.echo(f"  {bucket}: {n}")
    click.echo("By type:")
    for sample_type, n in by_type.items():
        click.echo(f"  {sample_type}: {n}")


if __name__ == "__main__":
    main()
