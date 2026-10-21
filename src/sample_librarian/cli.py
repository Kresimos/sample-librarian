from __future__ import annotations

from pathlib import Path

import click

from sample_librarian.classify.classifier import load_taxonomy
from sample_librarian.config import ConfigError, load_settings
from sample_librarian.db import repository
from sample_librarian.pipeline.bpm_remediation import apply_bpm_fills, plan_bpm_fills
from sample_librarian.pipeline.inbox_rescan import run_inbox_rescan
from sample_librarian.pipeline.initial_sweep import run_apply_sweep, run_dry_run_sweep
from sample_librarian.pipeline.rename_remediation import apply_renames, plan_renames
from sample_librarian.pipeline.retag_remediation import apply_retags, plan_retags
from sample_librarian.pipeline.tempo_remediation import apply_tempo_fixes, plan_tempo_fixes
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


@main.command("fix-mangled-names")
@_config_option
@click.option(
    "--apply",
    "do_apply",
    is_flag=True,
    default=False,
    help="Actually rename the files and update the database, instead of just reporting.",
)
@click.option(
    "--yes",
    "skip_confirm",
    is_flag=True,
    default=False,
    help="Skip the interactive confirmation prompt for --apply (for scripting).",
)
def fix_mangled_names_cmd(config_path: Path, do_apply: bool, skip_confirm: bool) -> None:
    """Fix already-organized files whose display name is a whole Windows-style
    backslash path baked into one flat filename (e.g. some Cymatics packs
    extract this way). Dry-run by default -- add --apply to actually rename.
    Category tags (drum/synth/chord/etc.) are untouched either way, since they
    were already derived from this same folder-name context at scan time.
    """
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    if do_apply and not skip_confirm:
        click.echo("This will rename real files in the library and update the database.")
        click.confirm("Have you already reviewed a dry run of this? Proceed?", abort=True)

    with repository.open_db(settings.db_path) as conn:
        plans = plan_renames(conn)

        if not plans:
            click.echo("Nothing to fix.")
            return

        if not do_apply:
            click.echo(f"Would fix {len(plans)} file(s):")
            for plan in plans:
                click.echo(f"  {plan.old_path.name}\n  -> {plan.new_path.name}")
            return

        report = apply_renames(conn, settings, plans)

    click.echo(f"Renamed {report.renamed_count} of {len(plans)} file(s)")
    click.echo(f"  scan_run_id: {report.scan_run_id} (use this with `samplelib undo` if needed)")
    if report.errors:
        click.echo(f"  errors: {len(report.errors)}")
        for path, error in report.errors:
            click.echo(f"    {path}: {error}", err=True)


@main.command("fix-tempo")
@_config_option
@click.option(
    "--apply",
    "do_apply",
    is_flag=True,
    default=False,
    help="Actually change the database and files, instead of just reporting.",
)
@click.option(
    "--yes",
    "skip_confirm",
    is_flag=True,
    default=False,
    help="Skip the interactive confirmation prompt for --apply (for scripting).",
)
def fix_tempo_cmd(config_path: Path, do_apply: bool, skip_confirm: bool) -> None:
    """Correct filename-derived tempos that were actually catalog/index
    numbers (a one-shot's number, or anything under 50 BPM -- see CLAUDE.md
    for how these were identified), and bake Logic Pro's "Smart Tempo" chunk
    into every WAV with a genuinely known tempo, so Logic's "File Tempo"
    field works on a plain drag. Dry-run by default -- add --apply to
    actually change anything. Fully undo-able like every other real action
    here.
    """
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    if do_apply and not skip_confirm:
        click.echo("This will change bpm data in the database and rewrite embedded tempo chunks in real files.")
        click.confirm("Have you already reviewed a dry run of this? Proceed?", abort=True)

    with repository.open_db(settings.db_path) as conn:
        plan = plan_tempo_fixes(conn)

        if not plan.clear_actions and not plan.bake_actions:
            click.echo("Nothing to fix.")
            return

        if not do_apply:
            click.echo(f"Would clear {len(plan.clear_actions)} incorrect tempo(s):")
            for action in plan.clear_actions:
                click.echo(f"  {action.path.name}  bpm={action.previous_bpm:.0f} ({action.reason})")
            click.echo(f"Would bake Smart Tempo into {len(plan.bake_actions)} file(s)")
            return

        report = apply_tempo_fixes(conn, settings, plan)

    click.echo(f"Cleared {report.cleared_count} incorrect tempo(s)")
    click.echo(f"Baked Smart Tempo into {report.baked_count} file(s)")
    click.echo(f"  scan_run_id: {report.scan_run_id} (use this with `samplelib undo` if needed)")
    if report.errors:
        click.echo(f"  errors: {len(report.errors)}")
        for path, error in report.errors:
            click.echo(f"    {path}: {error}", err=True)


@main.command("fix-bpm")
@_config_option
@click.option(
    "--apply",
    "do_apply",
    is_flag=True,
    default=False,
    help="Actually change the database, instead of just reporting.",
)
@click.option(
    "--yes",
    "skip_confirm",
    is_flag=True,
    default=False,
    help="Skip the interactive confirmation prompt for --apply (for scripting).",
)
def fix_bpm_cmd(config_path: Path, do_apply: bool, skip_confirm: bool) -> None:
    """Re-extract tempo/key for already-indexed samples that currently have
    none, using the improved metadata reader: AIFF Apple Loops (MARK-chunk
    "Tempo:" marker), CAF Apple Loops (beat count / duration + key
    descriptor), and WAV ACID chunks that carry a beat count but a zeroed
    tempo field. DB-only -- never touches a file, and only fills a column
    that was NULL. Dry-run by default. Fully undo-able.

    Run `samplelib fix-tempo` afterwards to bake Logic's Smart Tempo chunk
    into the WAVs that just gained a tempo.
    """
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    if do_apply and not skip_confirm:
        click.echo("This will fill in bpm/key data in the database (not files).")
        click.confirm("Have you already reviewed a dry run of this? Proceed?", abort=True)

    with repository.open_db(settings.db_path) as conn:
        actions = plan_bpm_fills(conn)

        if not actions:
            click.echo("Nothing to fill.")
            return

        bpm_n = sum(1 for a in actions if a.new_bpm is not None)
        key_n = sum(1 for a in actions if a.new_key is not None)

        if not do_apply:
            click.echo(f"Would fill bpm for {bpm_n} sample(s), key for {key_n} sample(s):")
            for a in actions[:40]:
                bits = []
                if a.new_bpm is not None:
                    bits.append(f"bpm={a.new_bpm:.1f}[{a.new_bpm_source}]")
                if a.new_key is not None:
                    bits.append(f"key={a.new_key}[{a.new_key_source}]")
                click.echo(f"  {a.original_filename}  {' '.join(bits)}")
            if len(actions) > 40:
                click.echo(f"  ... and {len(actions) - 40} more")
            return

        report = apply_bpm_fills(conn, settings, actions)

    click.echo(f"Filled bpm for {report.bpm_filled} sample(s), key for {report.key_filled} sample(s)")
    click.echo(f"  scan_run_id: {report.scan_run_id} (use this with `samplelib undo` if needed)")
    if report.errors:
        click.echo(f"  errors: {len(report.errors)}")
        for path, error in report.errors:
            click.echo(f"    {path}: {error}", err=True)


@main.command("fix-tags")
@_config_option
@click.option(
    "--taxonomy",
    "taxonomy_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    default=DEFAULT_TAXONOMY_PATH,
    show_default=True,
)
@click.option(
    "--apply",
    "do_apply",
    is_flag=True,
    default=False,
    help="Actually change the database, instead of just reporting.",
)
@click.option(
    "--yes",
    "skip_confirm",
    is_flag=True,
    default=False,
    help="Skip the interactive confirmation prompt for --apply (for scripting).",
)
def fix_tags_cmd(config_path: Path, taxonomy_path: Path, do_apply: bool, skip_confirm: bool) -> None:
    """Recompute every already-swept sample's tags against the current
    config/taxonomy.yaml (and vendor_name-to-tag mirroring) -- for backfilling
    new taxonomy rules or the creator/vendor tag onto files that were
    classified before those rules existed. Never touches files, only the
    tags table. Dry-run by default -- add --apply to actually change
    anything. Fully undo-able like every other real action here.
    """
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    taxonomy_rules = load_taxonomy(taxonomy_path)

    if do_apply and not skip_confirm:
        click.echo("This will change tag data in the database (not files).")
        click.confirm("Have you already reviewed a dry run of this? Proceed?", abort=True)

    with repository.open_db(settings.db_path) as conn:
        plans = plan_retags(conn, taxonomy_rules)

        if not plans:
            click.echo("Nothing to fix.")
            return

        if not do_apply:
            click.echo(f"Would retag {len(plans)} file(s):")
            for plan in plans:
                old = ",".join(plan.old_tags) or "-"
                new = ",".join(plan.new_tags) or "-"
                click.echo(f"  {Path(plan.current_path).name}\n    {old}\n    -> {new}")
            return

        report = apply_retags(conn, settings, plans)

    click.echo(f"Retagged {report.retagged_count} of {len(plans)} file(s)")
    click.echo(f"  scan_run_id: {report.scan_run_id} (use this with `samplelib undo` if needed)")
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
