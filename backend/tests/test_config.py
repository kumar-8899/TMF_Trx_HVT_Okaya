"""Config service (CORE.md §1, PRINCIPLES §4)."""

import json

import pytest

from core.services.config import ConfigService, ConfigError


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
