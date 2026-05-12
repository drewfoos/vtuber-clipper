from clipper.captions import generate_window3_ass

WORDS = [
    {"start": 5.0, "end": 5.3, "word": "holy"},
    {"start": 5.4, "end": 5.7, "word": "no"},
    {"start": 5.8, "end": 6.2, "word": "way"},
    {"start": 6.3, "end": 6.6, "word": "that"},
    {"start": 6.7, "end": 7.0, "word": "just"},
    {"start": 7.1, "end": 7.6, "word": "happened"},
]


def test_window3_emits_one_dialogue_per_word():
    ass = generate_window3_ass(WORDS, clip_start=5.0, output_size=(1080, 1920))
    # One Dialogue line per word — each word is the "active" frame of a 3-word window.
    assert ass.count("Dialogue:") == len(WORDS)


def test_window3_active_word_has_color_override():
    ass = generate_window3_ass(WORDS, clip_start=5.0, output_size=(1080, 1920))
    # Active-word inline color override uses ASS \1c tag with yellow.
    assert "\\1c&H0000FFFF&" in ass or "\\1c&HFFD700&" in ass


def test_window3_includes_fade_in():
    ass = generate_window3_ass(WORDS, clip_start=5.0, output_size=(1080, 1920))
    # \fad(80,0) for a quick fade-in, no fade-out.
    assert "\\fad(" in ass


def test_window3_dialogue_times_are_clip_local():
    ass = generate_window3_ass(WORDS, clip_start=5.0, output_size=(1080, 1920))
    # First word starts at 5.0 source → 0.0 clip-local.
    assert "0:00:00.00" in ass
