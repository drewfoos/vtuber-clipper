import os
from pathlib import Path
from unittest.mock import patch

import pytest

from clipper.util.json_io import write_json


def test_atomic_write_creates_target(tmp_path: Path):
    p = tmp_path / "a.json"
    write_json(p, {"x": 1})
    assert p.exists()
    assert p.read_text(encoding="utf-8").strip().startswith("{")


def test_atomic_write_replaces_existing(tmp_path: Path):
    p = tmp_path / "a.json"
    write_json(p, {"v": 1})
    write_json(p, {"v": 2})
    import json
    assert json.loads(p.read_text(encoding="utf-8"))["v"] == 2


def test_atomic_write_leaves_no_temp_on_success(tmp_path: Path):
    p = tmp_path / "a.json"
    write_json(p, {"x": 1})
    siblings = list(tmp_path.iterdir())
    assert len(siblings) == 1
    assert siblings[0].name == "a.json"


def test_atomic_write_does_not_corrupt_on_crash(tmp_path: Path):
    p = tmp_path / "a.json"
    write_json(p, {"v": "first"})

    def boom(_src, _dst):
        raise RuntimeError("simulated mid-rename crash")

    with patch("os.replace", side_effect=boom), pytest.raises(RuntimeError):
        write_json(p, {"v": "second"})

    import json
    assert json.loads(p.read_text(encoding="utf-8"))["v"] == "first"
