import json
from pathlib import Path

from clipper.candidates import build_candidates, merge_peaks


def test_overlapping_audio_and_chat_merge_into_one():
    audio = [{"t_start": 10.0, "t_end": 12.0, "intensity": 14.0}]
    chat = [{"t_start": 11.0, "t_end": 13.0, "msg_count": 50, "hype_score": 80.0,
             "top_emotes": ["KEKW"]}]
    cands = merge_peaks(audio, chat, overlap_tolerance=5.0,
                        min_clip=25.0, max_clip=90.0, include_chat_only=True)
    assert len(cands) == 1
    c = cands[0]
    assert set(c["signals"]) == {"audio", "chat"}
    assert c["t_start"] <= 10.0
    assert c["t_end"] >= 13.0
    assert c["audio_intensity"] == 14.0
    assert c["chat_hype_score"] == 80.0


def test_chat_only_peak_when_no_audio_nearby():
    audio = []
    chat = [{"t_start": 50.0, "t_end": 53.0, "msg_count": 80, "hype_score": 90.0,
             "top_emotes": ["LULW"]}]
    cands = merge_peaks(audio, chat, overlap_tolerance=5.0,
                        min_clip=25.0, max_clip=90.0, include_chat_only=True)
    assert len(cands) == 1
    assert cands[0]["signals"] == ["chat_only"]


def test_chat_only_dropped_when_disabled():
    audio = []
    chat = [{"t_start": 50.0, "t_end": 53.0, "msg_count": 80, "hype_score": 90.0,
             "top_emotes": []}]
    cands = merge_peaks(audio, chat, overlap_tolerance=5.0,
                        min_clip=25.0, max_clip=90.0, include_chat_only=False)
    assert cands == []


def test_min_clip_pads_short_windows():
    audio = [{"t_start": 10.0, "t_end": 11.0, "intensity": 14.0}]
    chat = []
    cands = merge_peaks(audio, chat, overlap_tolerance=5.0,
                        min_clip=25.0, max_clip=90.0, include_chat_only=True)
    assert len(cands) == 1
    assert cands[0]["t_end"] - cands[0]["t_start"] >= 25.0


def test_max_clip_caps_long_windows():
    audio = [{"t_start": 10.0, "t_end": 200.0, "intensity": 14.0}]
    chat = []
    cands = merge_peaks(audio, chat, overlap_tolerance=5.0,
                        min_clip=25.0, max_clip=90.0, include_chat_only=True)
    assert len(cands) == 1
    assert cands[0]["t_end"] - cands[0]["t_start"] <= 90.0


def test_two_separate_peaks_produce_two_candidates():
    audio = [
        {"t_start": 10.0, "t_end": 12.0, "intensity": 14.0},
        {"t_start": 100.0, "t_end": 102.0, "intensity": 10.0},
    ]
    chat = [
        {"t_start": 10.5, "t_end": 12.5, "msg_count": 30, "hype_score": 60.0,
         "top_emotes": ["KEKW"]},
        {"t_start": 100.5, "t_end": 103.0, "msg_count": 40, "hype_score": 70.0,
         "top_emotes": ["POG"]},
    ]
    cands = merge_peaks(audio, chat, overlap_tolerance=5.0,
                        min_clip=25.0, max_clip=90.0, include_chat_only=True)
    assert len(cands) == 2


def test_build_candidates_writes_json(tmp_path: Path):
    audio_path = tmp_path / "audio_peaks.json"
    chat_path = tmp_path / "chat_peaks.json"
    audio_path.write_text(json.dumps([
        {"t_start": 10.0, "t_end": 12.0, "intensity": 14.0},
    ]), encoding="utf-8")
    chat_path.write_text(json.dumps([
        {"t_start": 11.0, "t_end": 13.0, "msg_count": 50, "hype_score": 80.0, "top_emotes": ["KEKW"]},
    ]), encoding="utf-8")
    out = build_candidates(audio_path, chat_path, tmp_path,
                           overlap_tolerance=5.0, min_clip=25.0, max_clip=90.0,
                           include_chat_only=True)
    cands = json.loads(out.read_text(encoding="utf-8"))
    assert len(cands) == 1
    assert cands[0]["id"] == "c001"
