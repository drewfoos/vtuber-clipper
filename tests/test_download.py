import re
from pathlib import Path

import pytest

from clipper.download import DownloadResult, parse_vod_id


def test_parse_vod_id_from_canonical_url():
    assert parse_vod_id("https://www.twitch.tv/videos/2762489406") == "2762489406"


def test_parse_vod_id_strips_trailing_query():
    assert parse_vod_id("https://www.twitch.tv/videos/2762489406?t=5m") == "2762489406"


def test_parse_vod_id_rejects_non_video_url():
    with pytest.raises(ValueError, match="not a Twitch VOD"):
        parse_vod_id("https://www.twitch.tv/somestreamer")


def test_parse_vod_id_rejects_garbage():
    with pytest.raises(ValueError):
        parse_vod_id("not even a url")
