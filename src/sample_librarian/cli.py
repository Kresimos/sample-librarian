from __future__ import annotations

from pathlib import Path

import click

from sample_librarian.classify.classifier import load_taxonomy
from sample_librarian.config import ConfigError, load_settings
from sample_librarian.db import repository
from sample_librarian.pipeline.inbox_rescan import run_inbox_rescan
from sample_librarian.pipeline.initial_sweep import run_apply_sweep, run_dry_run_sweep
from sample_librarian.pipeline.vendor_rescan import run_vendor_rescan
from sample_librarian.undo import UndoError, undo_scan_run

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
@click.option(
    "--apply",
    "do_apply",
    is_flag=True,
    default=False,
    help="Actually move/symlink files and write tempo metadata, instead of just reporting.",
)
@click.option(
    "--yes",
    "skip_confirm",
    is_flag=True,
    default=False,
    help="Skip the interactive confirmation prompt for --apply (for scripting).",
)
def scan_cmd(
    config_path: Path, taxonomy_path: Path, limit: int | None, do_apply: bool, skip_confirm: bool
) -> None:
    """Sweep scan_roots and report what it would do. Dry-run by default --
    add --apply to actually move/symlink files and write tempo metadata.

    Always review a dry run before using --apply. Every real run writes a
    manifest that `samplelib undo <scan_run_id>` can fully reverse.
    """
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    taxonomy_rules = load_taxonomy(taxonomy_path)

    if do_apply and not skip_confirm:
        click.echo("This will move real files and write metadata into them.")
        click.confirm("Have you already reviewed a dry run (`samplelib scan`) of this? Proceed?", abort=True)

    with repository.open_db(settings.db_path) as conn:
        if do_apply:
            report = run_apply_sweep(settings, taxonomy_rules, conn)
        else:
            report = run_dry_run_sweep(settings, taxonomy_rules, conn)

    verb = "Applied" if do_apply else "Scanned (dry run)"
    click.echo(f"{verb}: {report.files_scanned} audio file(s)")
    label = "symlinked" if do_apply else "would symlink only"
    click.echo(f"  vendor ({label}): {report.vendor_count}")
    label = "moved + stub-symlinked" if do_apply else "would move + stub-symlink"
    click.echo(f"  orphan ({label}): {report.orphan_count}")
    if report.errors:
        click.echo(f"  errors: {len(report.errors)}")
    if do_apply:
        click.echo(f"  scan_run_id: {report.scan_run_id} (use this with `samplelib undo` if needed)")

    shown = report.actions[:limit] if limit else report.actions
    for action in shown:
        tags = ",".join(action.tags) if action.tags else "-"
        bpm = f"{action.bpm:.0f}bpm[{action.bpm_source}]" if action.bpm else "-"
        key = f"{action.musical_key}[{action.key_source}]" if action.musical_key else "-"
        click.echo(
            f"  [{action.bucket:6}] {action.source_path} -> {action.target_path}\n"
            f"           tags={tags} bpm={bpm} key={key}"
        )

    for path, error in report.errors:
        click.echo(f"  ERROR {path}: {error}", err=True)


@main.command("rescan-inbox")
@_config_option
@click.option(
    "--taxonomy",
    "taxonomy_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=DEFAULT_TAXONOMY_PATH,
    show_default=True,
)
def rescan_inbox_cmd(config_path: Path, taxonomy_path: Path) -> None:
    """Process everything currently in inbox/, moving results into unsorted/
    and leaving inbox/ empty again. Safe to run any time -- always real
    (no dry-run mode), since inbox/ only ever contains things you deliberately
    put there to be organized.
    """
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    taxonomy_rules = load_taxonomy(taxonomy_path)

    with repository.open_db(settings.db_path) as conn:
        report = run_inbox_rescan(settings, taxonomy_rules, conn)

    click.echo(f"Processed {report.files_scanned} file(s) from inbox/")
    click.echo(f"  moved into unsorted/: {report.orphan_count}")
    if report.errors:
        click.echo(f"  errors: {len(report.errors)}")
        for path, error in report.errors:
            click.echo(f"    {path}: {error}", err=True)


@main.command("rescan-vendor")
@_config_option
@click.option(
    "--taxonomy",
    "taxonomy_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=DEFAULT_TAXONOMY_PATH,
    show_default=True,
)
def rescan_vendor_cmd(config_path: Path, taxonomy_path: Path) -> None:
    """Re-symlink vendor_roots into the library, picking up anything newly
    installed. Manual-only by design -- run this yourself after installing a
    new sample library, it never runs on its own. Safe to re-run any time:
    already-correct symlinks are a no-op, only genuinely new files change.
    """
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    taxonomy_rules = load_taxonomy(taxonomy_path)

    with repository.open_db(settings.db_path) as conn:
        report = run_vendor_rescan(settings, taxonomy_rules, conn)

    click.echo(f"Checked {report.files_scanned} vendor file(s)")
    click.echo(f"  symlinked (new or confirmed): {report.vendor_count}")
    if report.errors:
        click.echo(f"  errors: {len(report.errors)}")
        for path, error in report.errors:
            click.echo(f"    {path}: {error}", err=True)


@main.command("undo")
@_config_option
@click.argument("scan_run_id", type=int)
@click.option("--yes", "skip_confirm", is_flag=True, default=False, help="Skip the confirmation prompt.")
def undo_cmd(config_path: Path, scan_run_id: int, skip_confirm: bool) -> None:
    """Reverse a real (non-dry-run) scan_run: moves files back, removes
    symlinks, and restores tempo metadata to what it was before.
    """
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    if not skip_confirm:
        click.confirm(f"Undo scan_run {scan_run_id}? This moves files back and removes what it added.", abort=True)

    with repository.open_db(settings.db_path) as conn:
        try:
            report = undo_scan_run(conn, scan_run_id)
        except UndoError as exc:
            raise click.ClickException(str(exc)) from exc

    click.echo(f"Reversed {report.reversed_count} action(s)")
    if report.skipped:
        click.echo(f"  could not reverse: {len(report.skipped)}")
        for entry, error in report.skipped:
            click.echo(f"    {entry.action} {entry.dest}: {error}", err=True)


@main.command("search")
@_config_option
@click.option("--text", default=None, help="Free text against filename or tags.")
@click.option("--tag", "tags", multiple=True, help="Require this tag (repeat --tag for multiple, AND semantics).")
@click.option("--bpm-min", type=float, default=None)
@click.option("--bpm-max", type=float, default=None)
@click.option("--key", "musical_key", default=None, help="Exact musical key, e.g. C#min.")
def search_cmd(
    config_path: Path,
    text: str | None,
    tags: tuple[str, ...],
    bpm_min: float | None,
    bpm_max: float | None,
    musical_key: str | None,
) -> None:
    """Quick terminal search against the library, same filters the Stage 2
    app uses. Mostly useful for debugging without opening the GUI.
    """
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    with repository.open_db(settings.db_path) as conn:
        rows = repository.search_samples(
            conn,
            text=text,
            tags=list(tags) or None,
            bpm_min=bpm_min,
            bpm_max=bpm_max,
            musical_key=musical_key,
        )

        click.echo(f"{len(rows)} result(s)")
        for row in rows:
            bpm = f"{row['bpm']:.0f}bpm" if row["bpm"] is not None else "-"
            key = row["musical_key"] or "-"
            row_tags = ",".join(repository.tags_for_sample(conn, row["id"])) or "-"
            click.echo(f"  [{row['bucket']:6}] {row['cleaned_filename']:40} bpm={bpm:>6} key={key:6} tags={row_tags}")
            click.echo(f"           {row['current_path']}")


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
        by_tag = repository.tag_counts(conn)

    click.echo(f"Total samples in library: {total}")
    for bucket, n in by_bucket.items():
        click.echo(f"  {bucket}: {n}")
    click.echo("By tag:")
    for tag, n in by_tag.items():
        click.echo(f"  {tag}: {n}")


if __name__ == "__main__":
    main()
