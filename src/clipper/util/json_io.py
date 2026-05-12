import json
from pathlib import Path
from typing import Any, Iterator

def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    path.write_text(json.dumps(data, indent=indent), encoding="utf-8")

def read_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
