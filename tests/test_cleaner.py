from sample_librarian.naming.cleaner import clean_filename, make_unique


def test_strips_bpm_and_key_tokens():
    result = clean_filename("gritty_analog_breakbeat_120bpm_Cmin")
    assert "120" not in result
    assert "bpm" not in result.lower()
    assert "cmin" not in result.lower()
    assert "Gritty" in result and "Analog" in result and "Breakbeat" in result


def test_underscores_and_dashes_become_spaces():
    result = clean_filename("deep-house_bassline--loop")
    assert result == "Deep House Bassline Loop"


def test_strips_junk_brackets():
    result = clean_filename("[FREE] Vocal Chop (Wet)")
    assert "[" not in result and "]" not in result and "(" not in result and ")" not in result


def test_collapses_whitespace_and_edge_punctuation():
    result = clean_filename("  __weird---name__  ")
    assert result == "Weird Name"


def test_keeps_acronyms_uppercase():
    result = clean_filename("FX_Riser_LFO_sweep")
    assert "FX" in result
    assert "LFO" in result


def test_empty_after_cleanup_falls_back_to_untitled():
    assert clean_filename("___120bpm___") == "untitled"


def test_decodes_url_percent_encoding():
    result = clean_filename("Track%20Name%20-%20SoundLoadMate.com")
    assert "%20" not in result
    assert result == "Track Name Soundloadmate.com"


def test_make_unique_no_collision():
    assert make_unique("Kick Heavy", set()) == "Kick Heavy"


def test_make_unique_appends_suffix_on_collision():
    existing = {"Kick Heavy", "Kick Heavy 2"}
    assert make_unique("Kick Heavy", existing) == "Kick Heavy 3"
