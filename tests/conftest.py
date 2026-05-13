import json
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.fixture
def fixture_work_dir(tmp_path: Path) -> Path:
    """Synthetic work/<vod_id>/ directory with all upstream files in place."""
    work = tmp_path / "work" / "vod_test"
    work.mkdir(parents=True)
    shutil.copy(FIXTURES / "fixture_video.mp4", work / "video.mp4")
    shutil.copy(FIXTURES / "ranked.sample.json", work / "ranked.json")
    shutil.copy(FIXTURES / "transcript.sample.json", work / "transcript.json")
    shutil.copy(FIXTURES / "audio_peaks.sample.json", work / "audio_peaks.json")
    shutil.copy(FIXTURES / "chat_peaks.sample.json", work / "chat_peaks.json")
    return work

@pytest.fixture
def fixture_out_dir(tmp_path: Path) -> Path:
    out = tmp_path / "out" / "vod_test"
    out.mkdir(parents=True)
    return out
