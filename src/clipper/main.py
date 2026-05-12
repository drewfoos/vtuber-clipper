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


def _serve(work_dir: Path, out_root: Path, port: int, idle_timeout_s: int = 1800) -> None:
    import asyncio, time
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

    async def watcher():
        while not server.started:
            await asyncio.sleep(0.1)
        while True:
            await asyncio.sleep(5)
            if app.state.should_exit:
                server.should_exit = True
                return
            idle = time.monotonic() - app.state.last_request_at
            if idle > idle_timeout_s:
                logger.info(f"Idle {idle:.0f}s — shutting down")
                server.should_exit = True
                return

    async def main_loop():
        await asyncio.gather(server.serve(), watcher())

    asyncio.run(main_loop())


@cli.command()
@click.argument("url")
@click.option("--work-root", default="work", type=click.Path(path_type=Path))
@click.option("--out-root", default="out", type=click.Path(path_type=Path))
@click.option("--no-review", is_flag=True, help="Skip launching review UI; run upstream + preview only.")
@click.option("--ranker", "ranker_override", default=None, help="Override config: 'ollama' or 'anthropic'.")
def run(url: str, work_root: Path, out_root: Path, no_review: bool, ranker_override: str | None) -> None:
    """Pipeline: download, transcribe, detect peaks, rank, preview, review."""
    from clipper.audio_peaks import detect_audio_peaks
    from clipper.candidates import build_candidates
    from clipper.chat import download_chat
    from clipper.chat_peaks import detect_chat_peaks
    from clipper.config import load_config
    from clipper.download import download_vod
    from clipper.rank import AnthropicRanker, OllamaRanker, rank_candidates
    from clipper.transcribe import transcribe

    cfg = load_config()
    work_root = Path(work_root)
    out_root = Path(out_root)
    work_root.mkdir(parents=True, exist_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)

    logger.info("Stage 1/8: download")
    dl = download_vod(url, work_root, quality=cfg.download.quality)
    work_dir = dl.video_path.parent

    logger.info("Stage 2/8: chat")
    download_chat(url, work_dir)

    logger.info("Stage 3/8: transcribe")
    transcribe(dl.audio_path, work_dir,
               model_size=cfg.transcribe.model,
               device=cfg.transcribe.device,
               compute_type=cfg.transcribe.compute_type)

    logger.info("Stage 4/8: audio peaks")
    detect_audio_peaks(dl.audio_path, work_dir,
                       db_above_baseline=cfg.audio_peaks.db_above_baseline,
                       min_duration_seconds=cfg.audio_peaks.min_duration_seconds,
                       merge_gap_seconds=cfg.audio_peaks.merge_gap_seconds)

    logger.info("Stage 5/8: chat peaks")
    detect_chat_peaks(work_dir / "chat.jsonl", dl.duration_seconds, work_dir,
                      bucket_seconds=cfg.chat_peaks.bucket_seconds,
                      min_prominence_multiplier=cfg.chat_peaks.min_prominence_multiplier,
                      min_gap_seconds=cfg.chat_peaks.min_gap_seconds,
                      hype_regex=cfg.chat_peaks.hype_regex)

    logger.info("Stage 6/8: candidates")
    build_candidates(work_dir / "audio_peaks.json", work_dir / "chat_peaks.json", work_dir,
                     overlap_tolerance=cfg.candidates.overlap_tolerance_seconds,
                     min_clip=cfg.candidates.min_clip_seconds,
                     max_clip=cfg.candidates.max_clip_seconds,
                     include_chat_only=cfg.candidates.include_chat_only)

    logger.info("Stage 7/8: rank")
    backend = ranker_override or cfg.rank.backend
    if backend == "anthropic":
        ranker_impl = AnthropicRanker(model=cfg.rank.anthropic_model)
    else:
        ranker_impl = OllamaRanker(model=cfg.rank.ollama_model)
    rank_candidates(work_dir, ranker_impl,
                    min_score=cfg.rank.min_score,
                    max_clips=cfg.rank.max_clips)

    logger.info("Stage 8/8: preview export + review")
    preview_export(work_dir)

    if no_review:
        click.echo(f"Pipeline complete. Run 'clipper review {dl.vod_id}' to review.")
        return

    port = find_free_port()
    review_url = f"http://localhost:{port}"
    logger.info(f"Opening {review_url}")
    webbrowser.open(review_url)
    _serve(work_dir, out_root / dl.vod_id, port)


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
