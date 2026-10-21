from sample_librarian.audio.filename_regex import extract_bpm, extract_key, strip_recognized_tokens


def test_bpm_tagged_variants():
    assert extract_bpm("Gritty Break 120BPM.wav") == 120.0
    assert extract_bpm("groove_140-bpm_final.wav") == 140.0
    assert extract_bpm("track 98 bpm.wav") == 98.0


def test_bare_numbers_are_never_treated_as_bpm():
    # A bare number is inherently ambiguous with a loop/take/variation index
    # (both extremely common in real sample-pack naming) -- there's no
    # reliable way to tell "the 58th loop" from "58 BPM" from the filename
    # alone, so this deliberately never guesses without an explicit "bpm" tag.
    assert extract_bpm("Snare Loop 58.wav") is None
    assert extract_bpm("Deep_House_124_Loop.wav") is None
    assert extract_bpm("Deep_House_124.wav") is None
    assert extract_bpm("Sample_Pack_Vol_045.wav") is None


def test_bpm_absent():
    assert extract_bpm("Ethereal Dust Motes.wav") is None


def test_key_worded_variants():
    assert extract_key("Piano Loop Cmin.wav") == "Cmin"
    assert extract_key("Pad F# Major.wav") == "F#maj"
    assert extract_key("Bass_Dsharp_Minor.wav") == "D#min"


def test_key_short_form():
    assert extract_key("Chord_Am_120bpm.wav") == "Amin"
    assert extract_key("Lead_Csm_loop.wav") == "C#min"  # 's' is a recognized sharp shorthand


def test_key_absent():
    assert extract_key("Kick Heavy 01.wav") is None


def test_key_prefixed_with_literal_key_no_separator():
    # "KeyAmin" has no separator between "Key" and the note at all -- the
    # 'y' immediately before 'A' defeats the plain word-boundary check, so
    # this needs the dedicated _KEY_PREFIXED_* patterns.
    assert extract_key("Loop_KeyAmin_01.wav") == "Amin"
    assert extract_key("Loop_KeyCsharpMajor_01.wav") == "C#maj"


def test_key_prefixed_with_literal_key_and_separator():
    assert extract_key("Loop_Key-Amin_01.wav") == "Amin"
    assert extract_key("Loop_Key_Fmin_01.wav") == "Fmin"


def test_key_prefix_does_not_false_positive_on_keyboard():
    assert extract_key("Keyboard_Sample_01.wav") is None


def test_strip_recognized_tokens_removes_bpm_and_key():
    stripped = strip_recognized_tokens("Gritty Breakbeat 120BPM Cmin Final")
    assert "120" not in stripped
    assert "BPM" not in stripped
    assert "Cmin" not in stripped
    assert "Gritty" in stripped and "Breakbeat" in stripped and "Final" in stripped


def test_strip_recognized_tokens_leaves_unrelated_numbers():
    stripped = strip_recognized_tokens("Ethereal Dust Motes.wav")
    assert stripped.strip() == "Ethereal Dust Motes.wav"
