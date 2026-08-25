from pathlib import Path

from click.testing import CliRunner

from sample_librarian.cli import main

from .helpers import write_minimal_wav


def _write_config(tmp_path: Path, *, vendor_roots: list[Path] | None = None) -> Path:
    library_root = tmp_path / "library"
    scan_root = tmp_path / "scan"
    vendor_lines = "\n".join(f'  "{p}",' for p in (vendor_roots or []))
    config_path = tmp_path / "settings.toml"
    config_path.write_text(
        f"""
library_root = "{library_root}"
scan_roots = ["{scan_root}"]
vendor_roots = [
{vendor_lines}
]
audio_extensions = [".wav"]
"""
    )
    return config_path


def test_full_cli_workflow_end_to_end(tmp_path: Path):
    runner = CliRunner()
    scan_dir = tmp_path / "scan"
    vendor_dir = scan_dir / "VendorLib"
    write_minimal_wav(scan_dir / "Groovy_Bass_95bpm.wav")
    write_minimal_wav(vendor_dir / "kick.wav")
    config_path = _write_config(tmp_path, vendor_roots=[vendor_dir])

    result = runner.invoke(main, ["init", "--config", str(config_path)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(main, ["scan", "--config", str(config_path)])
    assert result.exit_code == 0, result.output
    assert "orphan (would move + stub-symlink): 1" in result.output
    assert "vendor (would symlink only): 1" in result.output

    # dry run must not have touched anything
    assert (scan_dir / "Groovy_Bass_95bpm.wav").exists()
    assert not (scan_dir / "Groovy_Bass_95bpm.wav").is_symlink()

    result = runner.invoke(main, ["scan", "--config", str(config_path), "--apply", "--yes"])
    assert result.exit_code == 0, result.output
    assert "orphan (moved + stub-symlinked): 1" in result.output
    scan_run_id = int(result.output.split("scan_run_id: ")[1].split()[0])

    library_root = tmp_path / "library"
    assert (library_root / "unsorted" / "Groovy Bass.wav").exists()
    assert (scan_dir / "Groovy_Bass_95bpm.wav").is_symlink()
    assert (library_root / "vendor" / "VendorLib" / "kick.wav").is_symlink()

    result = runner.invoke(main, ["stats", "--config", str(config_path)])
    assert result.exit_code == 0, result.output
    assert "Total samples in library: 2" in result.output

    # inbox rescan on an empty inbox is a harmless no-op
    result = runner.invoke(main, ["rescan-inbox", "--config", str(config_path)])
    assert result.exit_code == 0, result.output
    assert "Processed 0 file(s)" in result.output

    # drop something new straight into inbox/, as the user would going forward
    write_minimal_wav(library_root / "inbox" / "New_Find_140bpm.wav")
    result = runner.invoke(main, ["rescan-inbox", "--config", str(config_path)])
    assert result.exit_code == 0, result.output
    assert "moved into unsorted/: 1" in result.output
    assert (library_root / "unsorted" / "New Find.wav").exists()
    assert list((library_root / "inbox").iterdir()) == []

    # rescan-vendor picks up a newly-installed vendor file, and is a no-op otherwise
    write_minimal_wav(vendor_dir / "new_pack" / "snare.wav")
    result = runner.invoke(main, ["rescan-vendor", "--config", str(config_path)])
    assert result.exit_code == 0, result.output
    assert "symlinked (new or confirmed): 2" in result.output  # kick.wav re-confirmed + snare.wav new
    assert (library_root / "vendor" / "VendorLib" / "new_pack" / "snare.wav").is_symlink()

    # undo the original apply run: the bass file goes back to scan_dir
    result = runner.invoke(main, ["undo", str(scan_run_id), "--config", str(config_path), "--yes"])
    assert result.exit_code == 0, result.output
    assert (scan_dir / "Groovy_Bass_95bpm.wav").exists()
    assert not (scan_dir / "Groovy_Bass_95bpm.wav").is_symlink()
    assert not (library_root / "unsorted" / "Groovy Bass.wav").exists()


def test_scan_apply_requires_confirmation_without_yes(tmp_path: Path):
    runner = CliRunner()
    scan_dir = tmp_path / "scan"
    write_minimal_wav(scan_dir / "Track.wav")
    config_path = _write_config(tmp_path)

    runner.invoke(main, ["init", "--config", str(config_path)])
    result = runner.invoke(main, ["scan", "--config", str(config_path), "--apply"], input="n\n")

    assert result.exit_code != 0  # aborted
    assert (scan_dir / "Track.wav").exists()
    assert not (scan_dir / "Track.wav").is_symlink()


def test_search_cli_command(tmp_path: Path):
    runner = CliRunner()
    scan_dir = tmp_path / "scan"
    write_minimal_wav(scan_dir / "Deep_Kick_95bpm_Amin.wav")
    write_minimal_wav(scan_dir / "Bright_HiHat_140bpm.wav")
    config_path = _write_config(tmp_path)

    runner.invoke(main, ["init", "--config", str(config_path)])
    runner.invoke(main, ["scan", "--config", str(config_path), "--apply", "--yes"])

    result = runner.invoke(main, ["search", "--config", str(config_path), "--text", "kick"])
    assert result.exit_code == 0, result.output
    assert "1 result(s)" in result.output
    assert "Deep Kick.wav" in result.output

    result = runner.invoke(main, ["search", "--config", str(config_path), "--bpm-min", "100"])
    assert result.exit_code == 0, result.output
    assert "Bright Hihat.wav" in result.output
    assert "Deep Kick.wav" not in result.output
