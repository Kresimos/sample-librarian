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


def test_mangled_windows_backslash_path_keeps_only_last_segment():
    result = clean_filename(
        r"Cymatics - House - Starter Pack\Synth Loop Collection\Supersaw Loops\Cymatics - Super Saw Loop 15 - 128 BPM D#min"
    )
    assert "\\" not in result
    assert result == "Cymatics Super Saw Loop 15"


def test_escaped_quote_backslash_is_not_treated_as_path_separator():
    # e.g. a URL-decoded '\"God Save The Queen\"' -- backslash here escapes a
    # quote, it isn't a mangled Windows path, so nothing should be discarded.
    result = clean_filename(r'British National Anthem \"God Save The Queen\" EN')
    assert "British" in result and "Anthem" in result and "Queen" in result


def test_make_unique_no_collision():
    assert make_unique("Kick Heavy", set()) == "Kick Heavy"


def test_make_unique_appends_suffix_on_collision():
    # existing_stems_lower must be lowercased -- see make_unique's docstring.
    existing = {"kick heavy", "kick heavy 2"}
    assert make_unique("Kick Heavy", existing) == "Kick Heavy 3"


def test_make_unique_is_case_insensitive():
    # Regression: macOS's default filesystem is case-insensitive, so two
    # differently-cased cleaned names (e.g. from clean_filename preserving
    # an all-caps acronym-looking stem like "TOM1" vs title-casing "Tom1")
    # must still be detected as colliding, not treated as distinct.
    existing = {"tom1"}
    assert make_unique("TOM1", existing) == "TOM1 2"
    assert make_unique("Tom1", existing) == "Tom1 2"
