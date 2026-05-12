from pathlib import Path

from clipper.util.json_io import read_json, write_json, read_jsonl


def test_write_read_roundtrip(tmp_path: Path):
    p = tmp_path / "a.json"
    write_json(p, {"x": 1, "y": [2, 3]})
    assert read_json(p) == {"x": 1, "y": [2, 3]}


def test_read_jsonl_iterates_lines(tmp_path: Path):
    p = tmp_path / "a.jsonl"
    p.write_text('{"a": 1}\n{"a": 2}\n\n{"a": 3}\n', encoding="utf-8")
    assert list(read_jsonl(p)) == [{"a": 1}, {"a": 2}, {"a": 3}]
