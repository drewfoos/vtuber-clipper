from clipper.captions import generate_srt, generate_basic_ass

WORDS = [
    {"start": 5.0, "end": 5.3, "word": "holy"},
    {"start": 5.4, "end": 5.7, "word": "no"},
    {"start": 5.8, "end": 6.2, "word": "way"},
]

def test_srt_uses_clip_local_time():
    srt = generate_srt(WORDS, clip_start=5.0, max_words_per_cue=3)
    assert "00:00:00,000" in srt
    assert "holy no way" in srt
    assert "5.0" not in srt    # not source-local
    assert "-->" in srt

def test_srt_groups_words_into_cues():
    many = [{"start": i * 0.5, "end": i * 0.5 + 0.4, "word": f"w{i}"} for i in range(10)]
    srt = generate_srt(many, clip_start=0.0, max_words_per_cue=3)
    # 10 words / 3 per cue = 4 cues
    assert srt.count("-->") == 4

def test_basic_ass_has_styles_block():
    ass = generate_basic_ass(WORDS, clip_start=5.0, output_size=(1080, 1920))
    assert "[Script Info]" in ass
    assert "[V4+ Styles]" in ass
    assert "[Events]" in ass
    assert "Dialogue:" in ass

def test_ass_dialogue_uses_clip_local_time():
    ass = generate_basic_ass(WORDS, clip_start=5.0, output_size=(1080, 1920))
    # 0.0 - 0.3 in clip-local = first word "holy"
    assert "0:00:00.00" in ass
