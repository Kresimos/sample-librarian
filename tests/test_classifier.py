from pathlib import Path

import pytest

from sample_librarian.classify.classifier import classify, load_taxonomy

TAXONOMY_PATH = Path(__file__).parent.parent / "config" / "taxonomy.yaml"


@pytest.fixture(scope="module")
def rules():
    return load_taxonomy(TAXONOMY_PATH)


def test_kick_by_filename(rules):
    result = classify("Heavy_Kick_01.wav", [], rules)
    assert "kick" in result.tags
    assert "drum" in result.tags


def test_hihat_variants(rules):
    for name in ["Closed HiHat.wav", "hi-hat_bright.wav", "hh_tight.wav"]:
        result = classify(name, [], rules)
        assert "hihat" in result.tags, name


def test_breakbeat_by_folder_not_filename(rules):
    result = classify("Loop_09.wav", ["Break Loops"], rules)
    assert "breakbeat" in result.tags


def test_file_can_match_multiple_rules_at_once(rules):
    # No more first-match-wins: a guitar riff is genuinely both.
    result = classify("Guitar_Riff_Em.wav", [], rules)
    assert "guitar" in result.tags
    assert "melody" in result.tags


def test_no_match_returns_empty_tags(rules):
    result = classify("xyz_9f8a2.wav", [], rules)
    assert result.tags == ()


def test_word_boundary_avoids_false_positive(rules):
    # "bd" (kick) shouldn't match merely because it appears as a substring
    # inside an unrelated word like "Abduction".
    result = classify("Abduction_Sequence.wav", [], rules)
    assert "kick" not in result.tags


def test_plural_keyword_still_matches(rules):
    # "breakbeat" is the taxonomy keyword; real folders are often plural.
    result = classify("Loop_09.wav", ["Breakbeats", "Drum Loops"], rules)
    assert "breakbeat" in result.tags


def test_long_duration_is_tagged_song(rules):
    result = classify("Kick Drum Solo.mp3", [], rules, duration_seconds=210.0)
    assert result.tags == ("song",)


def test_duration_just_under_threshold_is_not_a_song(rules):
    result = classify("Heavy_Kick.wav", [], rules, duration_seconds=89.0)
    assert "kick" in result.tags
    assert "song" not in result.tags


def test_custom_song_threshold(rules):
    result = classify("Loop.wav", [], rules, duration_seconds=45.0, song_duration_threshold_seconds=30.0)
    assert result.tags == ("song",)


def test_loop_type_filename_keyword_wins(rules):
    assert "one-shot" in classify("Kick_OneShot.wav", [], rules).tags
    assert "one-shot" in classify("Kick_One_Shot.wav", [], rules).tags
    assert "one-shot" in classify("Kick_1shot.wav", [], rules).tags
    assert "loop" in classify("Ambient_Loop.wav", [], rules).tags


def test_loop_type_keyword_overrides_duration(rules):
    # explicit filename keyword should win even if duration suggests otherwise
    result = classify("Long_Kick_OneShot.wav", [], rules, duration_seconds=20.0)
    assert "one-shot" in result.tags
    assert "loop" not in result.tags


def test_loop_type_short_duration_is_one_shot(rules):
    result = classify("Random_Hit.wav", [], rules, duration_seconds=0.8)
    assert "one-shot" in result.tags


def test_loop_type_medium_duration_is_loop(rules):
    result = classify("Random_Phrase.wav", [], rules, duration_seconds=8.0)
    assert "loop" in result.tags


def test_loop_type_falls_back_to_matched_tags_when_duration_unknown(rules):
    assert "one-shot" in classify("Heavy_Kick.wav", [], rules).tags
    assert "loop" in classify("Groove_Break.wav", [], rules).tags


def test_loop_type_absent_when_no_signal_available(rules):
    result = classify("xyz_9f8a2.wav", [], rules)
    assert "loop" not in result.tags
    assert "one-shot" not in result.tags


def test_loop_type_drum_one_shot_with_long_sub_tail_still_one_shot(rules):
    # Regression: a real file found in ~/Downloads, "Kick_3_Sub_RedLine.wav",
    # is 5.9s (kick layered with a sub-bass tail) and was misclassified as a
    # loop under a flat 3s cutoff.
    result = classify("Kick_3_Sub_RedLine.wav", [], rules, duration_seconds=5.887)
    assert "kick" in result.tags
    assert "one-shot" in result.tags
    assert "loop" not in result.tags


def test_loop_type_non_drum_type_keeps_short_threshold(rules):
    # The generous threshold is specifically for drum-type one-shots; a
    # pad/synth/etc. at 5.9s with no other signal should still read as a loop.
    result = classify("Ambient_Texture.wav", [], rules, duration_seconds=5.887)
    assert "loop" in result.tags


def test_guitar_by_filename(rules):
    result = classify("Cymatics Vibrations Metal Guitar Loop 12 174 BPM D Maj.wav", [], rules)
    assert "guitar" in result.tags


def test_guitar_riff_does_not_leak_into_generic_melody_riff(rules):
    # "riff" alone (no "guitar") should still match melody, not guitar.
    result = classify("Cool_Riff_01.wav", [], rules)
    assert "melody" in result.tags
    assert "guitar" not in result.tags


def test_app_foley_tag_added_for_file_inside_app_bundle(rules):
    result = classify(
        "taskCompleted.mp3",
        ["media", "browser", "accessibilitySignal", "platform", "vs", "out", "app", "Resources",
         "Contents", "Visual Studio Code.app"],
        rules,
    )
    assert "app-foley" in result.tags


def test_app_foley_tag_absent_outside_app_bundle(rules):
    result = classify("Heavy_Kick.wav", ["Some Sample Pack"], rules)
    assert "app-foley" not in result.tags


def test_app_foley_tag_stacks_with_normal_classification(rules):
    result = classify("kick.wav", ["Sounds", "SomeApp.app"], rules)
    assert "kick" in result.tags
    assert "app-foley" in result.tags
    assert "drum" in result.tags  # normal taxonomy tags still present too


def test_app_foley_tag_still_applies_to_songs(rules):
    result = classify("theme.mp3", ["Resources", "SomeGame.app"], rules, duration_seconds=200.0)
    assert result.tags == ("song", "app-foley")


def test_loop_type_from_parent_folder_name(rules):
    # Common commercial sample pack layout: "<Pack Name>/Loops/foo.wav" and
    # "<Pack Name>/One Shots/foo.wav" -- the filename alone often carries no
    # loop/one-shot signal at all, only the containing folder does.
    result = classify("909_A.wav", ["Loops", "Kick Drum Pack"], rules)
    assert "loop" in result.tags

    result = classify("909_A.wav", ["One Shots", "Kick Drum Pack"], rules)
    assert "one-shot" in result.tags


def test_tags_are_deduplicated(rules):
    # "kick" appears both as the rule name and would collide if a filename
    # triggered the same tag twice via different routes -- must not duplicate.
    result = classify("Kick_Kick_Layered.wav", [], rules)
    assert result.tags.count("kick") == 1
