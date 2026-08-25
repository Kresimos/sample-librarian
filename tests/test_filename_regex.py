from sample_librarian.audio.filename_regex import extract_bpm, extract_key, strip_recognized_tokens


def test_bpm_tagged_variants():
    assert extract_bpm("Gritty Break 120BPM.wav") == 120.0
    assert extract_bpm("groove_140-bpm_final.wav") == 140.0
    assert extract_bpm("track 98 bpm.wav") == 98.0


def test_bpm_bare_fallback_in_range():
    assert extract_bpm("Deep_House_124_Loop.wav") == 124.0


def test_bpm_bare_out_of_range_ignored():
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


def test_strip_recognized_tokens_removes_bpm_and_key():
    stripped = strip_recognized_tokens("Gritty Breakbeat 120BPM Cmin Final")
    assert "120" not in stripped
    assert "BPM" not in stripped
    assert "Cmin" not in stripped
    assert "Gritty" in stripped and "Breakbeat" in stripped and "Final" in stripped


def test_strip_recognized_tokens_leaves_unrelated_numbers():
    stripped = strip_recognized_tokens("Ethereal Dust Motes.wav")
    assert stripped.strip() == "Ethereal Dust Motes.wav"
