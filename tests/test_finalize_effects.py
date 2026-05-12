import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipper.finalize import finalize
from clipper.preview_export import preview_export
from clipper.web import build_app


def _keep_only(work: Path, kept_ids: list[str]) -> None:
    client = TestClient(build_app(work))
    for cid in ("c001", "c002", "c003"):
        client.put(f"/api/clips/{cid}", json={"kept": cid in kept_ids})


def test_default_effects_applied_to_manifest(fixture_work_dir: Path, fixture_out_dir: Path):
    preview_export(fixture_work_dir)
    _keep_only(fixture_work_dir, ["c001"])
    finalize(fixture_work_dir, fixture_out_dir)
    manifest = json.loads((fixture_out_dir / "final" / "manifest.json").read_text())
    applied = set(manifest["clips"][0]["effects_applied"])
    # Default effects all enabled; captions plus the four effects.
    assert "captions" in applied
    assert "punch_zoom" in applied
    assert "hook_card" in applied  # c001 has hook_quality=9
    assert "reaction_zoom" in applied


def test_per_clip_effect_overrides_disable_specific_effect(fixture_work_dir, fixture_out_dir):
    preview_export(fixture_work_dir)
    client = TestClient(build_app(fixture_work_dir))
    client.put("/api/clips/c001", json={"effects": {"punch_zoom": False}})
    client.put("/api/clips/c002", json={"kept": False})
    client.put("/api/clips/c003", json={"kept": False})
    finalize(fixture_work_dir, fixture_out_dir)
    manifest = json.loads((fixture_out_dir / "final" / "manifest.json").read_text())
    applied = set(manifest["clips"][0]["effects_applied"])
    assert "punch_zoom" not in applied
    # Others remain.
    assert "hook_card" in applied
