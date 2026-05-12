from click.testing import CliRunner
from clipper.main import cli

def test_cli_help_works():
    res = CliRunner().invoke(cli, ["--help"])
    assert res.exit_code == 0
    assert "review" in res.output
    assert "finalize" in res.output

def test_finalize_subcommand_runs_headlessly(fixture_work_dir, fixture_out_dir):
    from clipper.web import build_app
    from fastapi.testclient import TestClient
    from clipper.preview_export import preview_export
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir))
    client.put("/api/clips/c002", json={"kept": False})
    client.put("/api/clips/c003", json={"kept": False})

    res = CliRunner().invoke(cli, [
        "finalize",
        "--work-dir", str(fixture_work_dir),
        "--out-dir", str(fixture_out_dir),
    ])
    assert res.exit_code == 0, res.output
    assert (fixture_out_dir / "final" / "manifest.json").exists()


def test_run_subcommand_no_longer_raises_unsupported(tmp_path):
    """The `run` subcommand should now exist and accept a URL — we just check that --help shows it."""
    from click.testing import CliRunner

    from clipper.main import cli

    res = CliRunner().invoke(cli, ["run", "--help"])
    assert res.exit_code == 0
    assert "url" in res.output.lower()
    assert "Pipeline" in res.output or "pipeline" in res.output
