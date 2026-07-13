"""Keystation licensing provider (secure-distribution P1).

Exercises the adapter with a fake `ks` (the SDK/DLL is not needed here). Proves the
fail-closed contract and the entitlement-key mapping the gate relies on.
"""

from contextlib import nullcontext

from core.services.licensing import Licensing
from core.services.licensing_keystation import (
    KeystationLicensing,
    build_licensing,
)


class _Status:
    def __init__(self, state="VALID", bootstrap="ACTIVE", tripwire_fired=False):
        self.state = state
        self.bootstrap = bootstrap
        self.tripwire_fired = tripwire_fired


class _FakeKs:
    """Minimal stand-in for the keystation SDK module."""

    def __init__(self, entitlements=(), status=None, raise_on_has=False):
        self._ent = set(entitlements)
        self._status = status or _Status()
        self._raise = raise_on_has

    def has(self, key):
        if self._raise:
            raise RuntimeError("core error")
        return key in self._ent

    def status(self):
        return self._status

    def session(self):
        return nullcontext()


def test_active_license_maps_module_to_plugin_key():
    ks = _FakeKs(entitlements={"plugin.report", "feature.report_db"})
    lic = KeystationLicensing(ks=ks).load_and_verify()
    assert lic.valid is True and lic.plan == "keystation"
    assert lic.allows_module("report") is True         # -> plugin.report
    assert lic.allows_module("analytics") is False      # absent = off
    assert lic.allows_feature("report_db") is True      # -> feature.report_db
    assert lic.allows_feature("shift") is False
    assert lic.allows_variant("report", "standard") is True   # no per-variant key = allow


def test_unactivated_fails_closed():
    ks = _FakeKs(entitlements={"plugin.report"}, status=_Status(bootstrap="UNACTIVATED"))
    lic = KeystationLicensing(ks=ks).load_and_verify()
    assert lic.valid is False and "not activated" in lic.reason
    assert lic.allows_module("report") is False         # entitlement present but not licensed
    assert lic.allows_feature("report_db") is False


def test_expired_state_fails_closed():
    ks = _FakeKs(entitlements={"plugin.report"}, status=_Status(state="EXPIRED"))
    lic = KeystationLicensing(ks=ks).load_and_verify()
    assert lic.valid is False and lic.allows_module("report") is False


def test_grace_state_still_licensed():
    ks = _FakeKs(entitlements={"plugin.report"}, status=_Status(state="GRACE"))
    lic = KeystationLicensing(ks=ks).load_and_verify()
    assert lic.valid is True and lic.allows_module("report") is True


def test_sdk_unavailable_fails_closed():
    # ks=None with no installed 'keystation' package -> _sdk() returns None
    lic = KeystationLicensing(ks=None).load_and_verify()
    assert lic.valid is False and lic.allows_module("anything") is False


def test_core_error_on_has_is_not_licensed():
    ks = _FakeKs(entitlements={"plugin.report"}, raise_on_has=True)
    lic = KeystationLicensing(ks=ks).load_and_verify()
    assert lic.valid is True                    # status ok
    assert lic.allows_module("report") is False  # but a core error on has() = fail-closed


def test_custom_key_map():
    ks = _FakeKs(entitlements={"plugin.daq_premium"})
    lic = KeystationLicensing(ks=ks, key_map={"daq": "plugin.daq_premium"}).load_and_verify()
    assert lic.allows_module("daq") is True


def test_variant_allowlist_when_mapped():
    ks = _FakeKs(entitlements={"plugin.auth", "plugin.auth.local_db"})
    lic = KeystationLicensing(ks=ks, key_map={
        "auth": "plugin.auth",
        "auth:local_db": "plugin.auth.local_db",   # entitled
        "auth:ldap": "plugin.auth.ldap",            # mapped but NOT entitled
    }).load_and_verify()
    assert lic.allows_variant("auth", "local_db") is True
    assert lic.allows_variant("auth", "ldap") is False       # mapped + entitlement absent = restricted
    assert lic.allows_variant("auth", "saml") is True        # unmapped = module gate decides = allow


def test_session_is_a_context_manager():
    ks = _FakeKs()
    with KeystationLicensing(ks=ks).session():
        pass


def test_factory_defaults_to_stub():
    prov = build_licensing({}, config=None, diag=None)
    assert isinstance(prov, Licensing)


def test_factory_selects_keystation():
    prov = build_licensing({"licensing": {"provider": "keystation"}}, config=None, diag=None)
    assert isinstance(prov, KeystationLicensing)
