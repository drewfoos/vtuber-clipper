"""Generate a 60-second 1920x1080 fixture video. Run once; output committed."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "fixture_video.mp4"

def main() -> None:
    if OUT.exists():
        print(f"{OUT} already exists, skipping")
        return
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=60",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=60",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(OUT),
    ]
    subprocess.run(cmd, check=True)
    print(f"Wrote {OUT}")

if __name__ == "__main__":
    sys.exit(main())
