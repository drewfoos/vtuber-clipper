import json
import webbrowser
from pathlib import Path

import click
import uvicorn

from clipper.finalize import finalize as finalize_call
from clipper.preview_export import preview_export
from clipper.util.logging import get_logger
from clipper.util.ports import find_free_port
from clipper.web import build_app

logger = get_logger(__name__)


@click.group()
def cli() -> None:
    """VTuber Clipper — pipeline + review UI."""


def _serve(work_dir: Path, out_root: Path, port: int) -> None:
    app = build_app(work_dir, out_root=out_root)
    server_info = {
        "port": port,
        "url": f"http://localhost:{port}",
        "vod_id": work_dir.name,
        "pid": __import__("os").getpid(),
    }
    (work_dir / "server.json").write_text(json.dumps(server_info))
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


@cli.command()
@click.argument("url")
@click.option("--work-root", default="work", type=click.Path(path_type=Path))
@click.option("--out-root", default="out", type=click.Path(path_type=Path))
@click.option("--no-review", is_flag=True, help="Skip launching review UI; run upstream + preview only.")
def run(url: str, work_root: Path, out_root: Path, no_review: bool) -> None:
    """Run the full pipeline for a Twitch VOD URL. Upstream stages NOT implemented in Plan A."""
    raise click.ClickException(
        "Upstream pipeline (download/transcribe/rank) is out of scope for Plan A. "
        "Use `clipper review <vod_id>` against a manually-prepared work dir, "
        "or build M1-M4 first."
    )


@cli.command()
@click.argument("vod_id")
@click.option("--work-root", default="work", type=click.Path(path_type=Path))
@click.option("--out-root", default="out", type=click.Path(path_type=Path))
def review(vod_id: str, work_root: Path, out_root: Path) -> None:
    """Open the review UI for an already-processed VOD."""
    work_dir = work_root / vod_id
    if not (work_dir / "ranked.json").exists():
        raise click.ClickException(f"No ranked.json in {work_dir}")
    preview_export(work_dir)
    port = find_free_port()
    url = f"http://localhost:{port}"
    logger.info(f"Opening {url}")
    webbrowser.open(url)
    _serve(work_dir, out_root / vod_id, port)


@cli.command()
@click.option("--work-dir", required=True, type=click.Path(path_type=Path, exists=True))
@click.option("--out-dir", required=True, type=click.Path(path_type=Path))
def finalize(work_dir: Path, out_dir: Path) -> None:
    """Headless finalize using the latest review_state.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = finalize_call(work_dir, out_dir)
    click.echo(f"Wrote {manifest}")


if __name__ == "__main__":
    cli()
