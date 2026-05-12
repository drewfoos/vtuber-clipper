import re
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, Response

RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")

def range_or_full(request: Request, path: Path, media_type: str = "video/mp4") -> Response:
    if not path.exists():
        from fastapi import HTTPException
        raise HTTPException(404, f"missing: {path.name}")
    range_header = request.headers.get("range")
    file_size = path.stat().st_size
    if not range_header:
        return FileResponse(path, media_type=media_type)
    m = RANGE_RE.match(range_header)
    if not m:
        return FileResponse(path, media_type=media_type)
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else file_size - 1
    end = min(end, file_size - 1)
    length = end - start + 1
    with path.open("rb") as f:
        f.seek(start)
        data = f.read(length)
    return Response(
        content=data,
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        },
    )
