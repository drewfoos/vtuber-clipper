from pathlib import Path

import pytest

from clipper.transcribe import transcribe


@pytest.mark.slow
def test_transcribe_writes_word_level_json(fixture_work_dir: Path):
    # Use the smallest whisper model so test wall-clock is bearable.
    out = transcribe(
        fixture_work_dir / "video.mp4",
        fixture_work_dir,
        model_size="tiny.en",
        device="cpu",
        compute_type="int8",
    )
    assert out.exists()
    import json
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "segments" in data


def test_transcribe_skips_if_output_exists(tmp_path: Path):
    out = tmp_path / "transcript.json"
    out.write_text('{"segments": []}', encoding="utf-8")
    result = transcribe(tmp_path / "nope.opus", tmp_path)
    assert result == out
