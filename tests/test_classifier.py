from pathlib import Path

import pytest

from sample_librarian.classify.classifier import classify, load_taxonomy

TAXONOMY_PATH = Path(__file__).parent.parent / "config" / "taxonomy.yaml"


@pytest.fixture(scope="module")
def rules():
    return load_taxonomy(TAXONOMY_PATH)


def test_kick_by_filename(rules):
    result = classify("Heavy_Kick_01.wav", [], rules)
    assert result.sample_type == "kick"
    assert "drum" in result.tags


def test_hihat_variants(rules):
    for name in ["Closed HiHat.wav", "hi-hat_bright.wav", "hh_tight.wav"]:
        result = classify(name, [], rules)
        assert result.sample_type == "hihat", name


def test_breakbeat_by_folder_not_filename(rules):
    result = classify("Loop_09.wav", ["Break Loops"], rules)
    assert result.sample_type == "breakbeat"


def test_first_matching_type_wins(rules):
    # "Kick" and "Drum Loop" both appear; kick is defined earlier in taxonomy.yaml.
    result = classify("Kick_in_Drum_Loop.wav", [], rules)
    assert result.sample_type == "kick"


def test_no_match_returns_none(rules):
    result = classify("xyz_9f8a2.wav", [], rules)
    assert result.sample_type is None
    assert result.tags == ()


def test_word_boundary_avoids_false_positive(rules):
    # "bd" (kick) shouldn't match merely because it appears as a substring
    # inside an unrelated word like "Abduction".
    result = classify("Abduction_Sequence.wav", [], rules)
    assert result.sample_type != "kick"


def test_plural_keyword_still_matches(rules):
    # "breakbeat" is the taxonomy keyword; real folders are often plural.
    result = classify("Loop_09.wav", ["Breakbeats", "Drum Loops"], rules)
    assert result.sample_type == "breakbeat"
