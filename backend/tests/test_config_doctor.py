"""config drift detection + the non-destructive config doctor."""

import json

from core.services.config import ConfigService
from tools.config_doctor import reconcile


def _auth(roles):
    return {"id": "auth", "variant": "local_db", "config": {"authenticator": "password", "roles": roles}}


def _write(cfg, name, data):
    (cfg / name).write_text(json.dumps(data), encoding="utf-8")


def _setup(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    base = {"schema_version": 1, "station": "st1", "license": "config/license.json"}
    # example: has the health module + HEALTH.* on super_admin
    _write(cfg, "app.example.json", {**base, "modules": [
        _auth({"super_admin": ["AUTH.*", "HEALTH.*"], "operator": ["TEST.RUN", "HEALTH.VIEW"]}),
        {"id": "health", "variant": "default", "config": {}},
    ]})
    # live: stale — no health module, super_admin lacks HEALTH.*, operator lacks HEALTH.VIEW
    _write(cfg, "app.json", {**base, "modules": [
        _auth({"super_admin": ["AUTH.*"], "operator": ["TEST.RUN"]}),
    ]})
    _write(cfg, "license.example.json", {"schema_version": 1, "entitlements": {
        "modules": {"auth": True, "health": True}, "variants": {"health": ["default"]}}})
    _write(cfg, "license.json", {"schema_version": 1, "entitlements": {"modules": {"auth": True}, "variants": {}}})
    return cfg


def test_config_drift_detects_all_categories(tmp_path):
    cfg = _setup(tmp_path)
    drift = ConfigService(cfg).config_drift()
    assert drift["modules"] == ["health"]
    assert "HEALTH.*" in drift["permissions"]["super_admin"]
    assert "HEALTH.VIEW" in drift["permissions"]["operator"]
    assert drift["license_modules"] == ["health"]


def test_doctor_dry_run_changes_nothing(tmp_path):
    cfg = _setup(tmp_path)
    before = (cfg / "app.json").read_text()
    changes = reconcile(cfg, apply=False)
    assert changes  # reported
    assert (cfg / "app.json").read_text() == before  # untouched


def test_doctor_apply_reconciles_additively(tmp_path):
    cfg = _setup(tmp_path)
    reconcile(cfg, apply=True)

    app = json.loads((cfg / "app.json").read_text())
    ids = [m["id"] for m in app["modules"]]
    assert "health" in ids
    roles = ConfigService._roles(app)
    assert "HEALTH.*" in roles["super_admin"] and "AUTH.*" in roles["super_admin"]  # added, kept
    assert "HEALTH.VIEW" in roles["operator"] and "TEST.RUN" in roles["operator"]

    lic = json.loads((cfg / "license.json").read_text())
    assert lic["entitlements"]["modules"]["health"] is True
    assert lic["entitlements"]["variants"]["health"] == ["default"]

    # idempotent: a second pass finds nothing
    assert reconcile(cfg, apply=True) == []
