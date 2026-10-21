from pathlib import Path

from sample_librarian.scanner.walker import iter_audio_files

from .helpers import write_minimal_wav


def test_excludes_a_subtree_entirely(tmp_path: Path):
    excluded = tmp_path / "NotSamples"
    kept = write_minimal_wav(tmp_path / "Kick.wav")
    write_minimal_wav(excluded / "Song.wav")

    found = set(iter_audio_files([tmp_path], [".wav"], exclude_roots=[excluded]))

    assert found == {kept}


def test_a_more_specific_scan_root_overrides_an_ancestor_exclusion(tmp_path: Path):
    # Mirrors excluding ~/Music/Logic wholesale (project-internal cruft)
    # while still wanting its Imports/ and Bounces/ subfolders scanned --
    # those get listed as their own scan_roots entries alongside the
    # broader exclusion.
    logic_root = tmp_path / "Logic"
    project_audio = write_minimal_wav(logic_root / "abba.logicx" / "Media" / "Audio Files" / "take1.wav")
    imports_audio = write_minimal_wav(logic_root / "Imports" / "cool_sample.wav")
    bounces_audio = write_minimal_wav(logic_root / "Bounces" / "my_song.wav")

    found = set(
        iter_audio_files(
            [logic_root / "Imports", logic_root / "Bounces"],
            [".wav"],
            exclude_roots=[logic_root],
        )
    )

    assert found == {imports_audio, bounces_audio}
    assert project_audio not in found


def test_symlinks_are_skipped(tmp_path: Path):
    real = write_minimal_wav(tmp_path / "Real.wav")
    link = tmp_path / "Link.wav"
    link.symlink_to(real)

    found = set(iter_audio_files([tmp_path], [".wav"]))

    assert found == {real}


def test_extension_filtering_is_case_insensitive(tmp_path: Path):
    wav = write_minimal_wav(tmp_path / "Kick.WAV")
    (tmp_path / "notes.txt").write_text("hi")

    found = set(iter_audio_files([tmp_path], [".wav"]))

    assert found == {wav}


def test_nonexistent_scan_root_is_skipped_not_an_error(tmp_path: Path):
    missing = tmp_path / "DoesNotExist"

    assert list(iter_audio_files([missing], [".wav"])) == []
