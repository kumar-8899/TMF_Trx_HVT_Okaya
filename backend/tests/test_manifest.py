"""Manifest loader (CORE.md §3.1)."""

import json

import pytest

from core.framework.manifest import ManifestError, ManifestLoader


def _write(modules_dir, mid, manifest):
    d = modules_dir / mid
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps(manifest))
    return d


VALID = {
    "schema_version": 1,
    "module": {
        "id": "hello",
        "version": "1.0.0",
        "contract_version": 1,
        "display_name": "Hello",
        "description": "ref module",
    },
    "entitlement_key": "hello",
    "variants": ["default"],
    "core_dependencies": ["bridge", "diagnostics", "web"],
    "contract_dependencies": [],
    "contributes": {"api_prefix": "/hello", "migrations": "migrations/"},
    "config_schema": "schemas/hello.config.schema.json",
}


def test_load_valid(tmp_path):
    d = _write(tmp_path, "hello", VALID)
    m = ManifestLoader(modules_dir=tmp_path).load("hello")
    assert m.id == "hello"
    assert m.entitlement_key == "hello"
    assert m.variants == ["default"]
    assert m.contributes.api_prefix == "/hello"
    assert m.config_schema_path == d / "schemas/hello.config.schema.json"
    assert m.migrations_path == d / "migrations"


def test_missing_is_loud(tmp_path):
    with pytest.raises(ManifestError):
        ManifestLoader(modules_dir=tmp_path).load("ghost")


def test_invalid_schema_rejected(tmp_path):
    bad = {**VALID, "schema_version": 2}
    _write(tmp_path, "hello", bad)
    with pytest.raises(ManifestError):
        ManifestLoader(modules_dir=tmp_path).load("hello")


def test_optional_paths_absent(tmp_path):
    minimal = {
        "schema_version": 1,
        "module": {"id": "m", "version": "1.0.0", "contract_version": 1, "display_name": "M"},
        "entitlement_key": "m",
        "variants": ["default"],
    }
    _write(tmp_path, "m", minimal)
    m = ManifestLoader(modules_dir=tmp_path).load("m")
    assert m.config_schema_path is None
    assert m.migrations_path is None
    assert m.core_dependencies == []
