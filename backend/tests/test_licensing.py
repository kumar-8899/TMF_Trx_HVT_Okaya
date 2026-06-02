"""Licensing stub (CORE.md §3.3, §4)."""

import json

from core.services.config import ConfigService
from core.services.licensing import License, Licensing


def _lic(**ent):
    return {
        "schema_version": 1,
        "plan": "pro",
        "issued_to": "Acme",
        "expires": "2099-01-01T00:00:00Z",
        "entitlements": ent,
    }


def test_allows_module_fail_closed():
    lic = License(_lic(modules={"auth": True, "report": False}), valid=True)
    assert lic.allows_module("auth") is True
    assert lic.allows_module("report") is False
    assert lic.allows_module("unknown") is False  # absent = off


def test_allows_variant_optional_allowlist():
    lic = License(_lic(modules={"auth": True}, variants={"auth": ["local_db"]}), valid=True)
    assert lic.allows_variant("auth", "local_db") is True
    assert lic.allows_variant("auth", "ldap") is False
    # no variants entry -> module gate already decided -> allow
    assert lic.allows_variant("recipe", "filesystem") is True


def test_invalid_license_blocks_everything():
    lic = License(_lic(modules={"auth": True}), valid=False, reason="expired")
    assert lic.allows_module("auth") is False
    assert lic.allows_feature("anything") is False


def test_expired_license_marked_invalid(tmp_path):
    raw = _lic(modules={"auth": True})
    raw["expires"] = "2000-01-01T00:00:00Z"
    (tmp_path / "license.json").write_text(json.dumps(raw))
    cfg = ConfigService(tmp_path)
    lic = Licensing(cfg).load_and_verify("license.json")
    assert lic.valid is False
    assert lic.reason == "expired"
    assert lic.allows_module("auth") is False


def test_valid_license_loads(tmp_path):
    (tmp_path / "license.json").write_text(json.dumps(_lic(modules={"hello": True})))
    cfg = ConfigService(tmp_path)
    lic = Licensing(cfg).load_and_verify("license.json")
    assert lic.valid is True
    assert lic.allows_module("hello") is True


def test_missing_license_fails_closed(tmp_path):
    cfg = ConfigService(tmp_path)
    lic = Licensing(cfg).load_and_verify("nope.json")
    assert lic.valid is False
    assert lic.allows_module("anything") is False
