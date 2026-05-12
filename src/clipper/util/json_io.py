import json
import os
from pathlib import Path
from typing import Any, Iterator


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    """Atomic write: serialize to a sibling tmp file, then os.replace into place.

    On Windows os.replace is atomic on NTFS; on POSIX it's a rename. Either way,
    a crash mid-write leaves the previous file intact.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=indent), encoding="utf-8")
    os.replace(tmp, path)


def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
