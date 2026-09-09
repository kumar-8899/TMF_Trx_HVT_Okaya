"""Config service (CORE.md §1, PRINCIPLES §4)."""

import json
from pathlib import Path

import pytest

from core.services.config import (
    ConfigError,
    ConfigService,
    migrate_cwd_state,
    resolve_state_path,
    state_root,
)


def test_ensure_live_copies_from_example(config_dir):
    cfg = ConfigService(config_dir)
    assert not (config_dir / "app.json").exists()
    live = cfg.ensure_live("app")
    assert live.exists()
    # second call is a no-op, keeps the live file
    assert cfg.ensure_live("app") == live


def test_load_app_validates(config_dir):
    cfg = ConfigService(config_dir)
    app = cfg.load_app()
    assert app["schema_version"] == 1
    assert app["station"]
    assert isinstance(app["modules"], list)


def test_bad_schema_version_rejected(config_dir):
    (config_dir / "app.json").write_text(
        json.dumps({"schema_version": 2, "station": "x", "license": "l", "modules": []})
    )
    cfg = ConfigService(config_dir)
    with pytest.raises(ConfigError):
        cfg.load_app()


def test_missing_file_is_loud(config_dir):
    cfg = ConfigService(config_dir)
    with pytest.raises(ConfigError):
        cfg.load_json(config_dir / "nope.json")


def test_example_only_modules_detects_drift(config_dir):
    cfg = ConfigService(config_dir)
    # live missing entirely -> nothing to compare
    assert cfg.example_only_modules() == []
    # stale live app.json with only hello; example has more
    (config_dir / "app.json").write_text(
        json.dumps({"schema_version": 1, "station": "st1", "license": "config/license.json",
                    "modules": [{"id": "hello", "variant": "default"}]})
    )
    drift = cfg.example_only_modules()
    assert "auth" in drift and "logs" in drift and "hello" not in drift


# --- state-path resolution (UPDATES.md §4.1 — never land config paths under run.dist) ---

def test_resolve_state_path_is_relative_to_the_external_deploy_root(tmp_path, monkeypatch):
    monkeypatch.setenv("TMF_STATE_DIR", str(tmp_path))
    # a relative config value resolves under <TMF_STATE_DIR>, NOT the process CWD
    assert resolve_state_path("data/recipes") == tmp_path / "data" / "recipes"
    assert state_root() == tmp_path
    # an absolute value is passed through untouched
    abs_p = tmp_path / "elsewhere" / "x"
    assert resolve_state_path(abs_p) == abs_p


def test_resolve_state_path_source_layout_matches_legacy_cwd(monkeypatch):
    monkeypatch.delenv("TMF_STATE_DIR", raising=False)
    from core.services.config import BACKEND_DIR
    assert resolve_state_path("data/recipes") == BACKEND_DIR / "data" / "recipes"


def test_migrate_cwd_state_rescues_a_dir_written_by_a_pre_fix_build(tmp_path, monkeypatch):
    """A frozen station that ran the old code left recipes at CWD/data/recipes; after the fix
    the corrected path is empty. The one-time migration copies them across."""
    monkeypatch.chdir(tmp_path)
    legacy = Path("data/recipes")
    (legacy / "r1").mkdir(parents=True)
    (legacy / "r1" / "meta.json").write_text('{"name": "R1"}', encoding="utf-8")
    resolved = tmp_path / "state" / "data" / "recipes"
    migrate_cwd_state("data/recipes", resolved)
    assert (resolved / "r1" / "meta.json").read_text() == '{"name": "R1"}'
    # idempotent: a second call with the target now populated does nothing / doesn't raise
    migrate_cwd_state("data/recipes", resolved)


def test_migrate_cwd_state_noop_when_target_exists_or_source_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    resolved = tmp_path / "state" / "data" / "recipes"
    resolved.mkdir(parents=True)
    (resolved / "keep").write_text("real", encoding="utf-8")
    (Path("data/recipes")).mkdir(parents=True)
    (Path("data/recipes") / "stale").write_text("old", encoding="utf-8")
    migrate_cwd_state("data/recipes", resolved)
    assert not (resolved / "stale").exists() and (resolved / "keep").read_text() == "real"
    # absolute source: never migrates
    migrate_cwd_state(str(tmp_path / "abs"), resolved)


def test_load_module_validates_against_schema(config_dir, tmp_path):
    schema = tmp_path / "m.schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["ttl"],
                "properties": {"ttl": {"type": "integer"}},
            }
        )
    )
    cfg = ConfigService(config_dir)
    assert cfg.load_module("m", {"ttl": 5}, schema) == {"ttl": 5}
    with pytest.raises(ConfigError):
        cfg.load_module("m", {"ttl": "nope"}, schema)
    # no schema -> passthrough
    assert cfg.load_module("m", {"x": 1}, None) == {"x": 1}
