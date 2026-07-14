"""Keystation-backed licensing provider (secure-distribution P1).

Implements the SAME contract as the stubbed `core.services.licensing.License` /
`Licensing` (CORE.md §3.3, §4) so the activation gate (`core/framework/gate.py`) is
unchanged — the swap is invisible to the gate, exactly as the stub's docstring
promised. Backed by the Keystation Python SDK (`keystation`, a cffi shim that "asks,
never asserts"): `ks.has()` / `ks.status()` / `ks.session()`.

Fail-closed everywhere: SDK missing, unactivated, expired, or any error ⇒ nothing is
licensed (mirrors the stub's `License({}, valid=False)`). The SDK / `ks` object is
injectable so this is fully testable without the native `keystation_core` DLL.

Entitlement mapping (the contract both sides share): a module's id maps to a namespaced
Keystation key — default `plugin.<module_id>`, overridable via `key_map`; features map to
`feature.<key>`. See docs/SECURE_DISTRIBUTION.md.
"""

from __future__ import annotations

import pathlib
from contextlib import nullcontext

# Keystation lease states that count as "licensed" (grace/warning still run; the SDK
# surfaces the notice). Anything else, or not ACTIVE-bootstrapped, is fail-closed.
_VALID_STATES = frozenset({"VALID", "WARNING", "GRACE", "REFRESHING"})


class KeystationLicense:
    """A `License` view over a Keystation status snapshot. Duck-compatible with
    `core.services.licensing.License` (`allows_module`/`allows_variant`/`allows_feature`,
    `.valid`, `.reason`, `.plan`)."""

    def __init__(self, ks, status, *, key_map: dict[str, str] | None = None,
                 diag=None) -> None:
        self._ks = ks
        self._status = status
        self._key_map = key_map or {}
        self._diag = diag
        # Whole-license validity: SDK present, bootstrap ACTIVE, state licensed.
        self.valid = bool(
            ks is not None and status is not None
            and getattr(status, "bootstrap", "") == "ACTIVE"
            and getattr(status, "state", "") in _VALID_STATES
        )
        self.reason = "" if self.valid else self._why(status)

    @staticmethod
    def _why(status) -> str:
        if status is None:
            return "keystation unavailable"
        boot = getattr(status, "bootstrap", "?")
        if boot != "ACTIVE":
            return f"not activated ({boot})"
        return f"lease {getattr(status, 'state', '?')}"

    @property
    def plan(self) -> str:
        return "keystation"

    def _has(self, key: str) -> bool:
        if not self.valid:
            return False
        try:
            return bool(self._ks.has(key))
        except Exception as exc:  # noqa: BLE001 — ask-never-assert: any error is not-licensed
            if self._diag:
                self._diag.error("licensing", "entitlement check failed", key=key, error=str(exc))
            return False

    def allows_module(self, module_id: str) -> bool:
        return self._has(self._key_map.get(module_id, f"plugin.{module_id}"))

    def allows_variant(self, module_id: str, variant_id: str) -> bool:
        # A per-variant entitlement is optional. If a specific key is mapped, it
        # restricts; otherwise the module-level gate already decided ⇒ allow.
        key = self._key_map.get(f"{module_id}:{variant_id}")
        if key is None:
            return self.valid
        return self._has(key)

    def allows_feature(self, key: str) -> bool:
        return self._has(f"feature.{key}")


class KeystationLicensing:
    """Provider mirroring `core.services.licensing.Licensing`: `load_and_verify()`
    returns a `KeystationLicense`. Also exposes `session()` (the runner wraps a test
    run in it — touch-point 2). `ks` is injectable for tests."""

    def __init__(self, diag=None, *, key_map: dict[str, str] | None = None,
                 core_lib: str | None = None, ks=None) -> None:
        self._diag = diag
        self._key_map = key_map
        self._core_lib = core_lib  # path to keystation_core.dll (ships with the app)
        self._ks = ks  # injected fake in tests; None ⇒ import the real SDK lazily

    def _sdk(self):
        if self._ks is not None:
            return self._ks
        try:
            import os
            if self._core_lib and not os.environ.get("KEYSTATION_CORE_LIB"):
                os.environ["KEYSTATION_CORE_LIB"] = self._core_lib
            import keystation as ks  # lazy — the app boots even without the SDK/DLL
            return ks
        except Exception as exc:  # noqa: BLE001 — missing SDK/DLL ⇒ fail-closed, never crash
            if self._diag:
                self._diag.error("licensing", "keystation SDK unavailable", error=str(exc))
            return None

    def load_and_verify(self, _license_path=None) -> KeystationLicense:
        ks = self._sdk()
        if ks is None:
            return KeystationLicense(None, None, key_map=self._key_map, diag=self._diag)
        try:
            status = ks.status()
        except Exception as exc:  # noqa: BLE001
            if self._diag:
                self._diag.error("licensing", "keystation status failed", error=str(exc))
            return KeystationLicense(None, None, key_map=self._key_map, diag=self._diag)
        if self._diag:
            self._diag.info("licensing", "keystation status",
                            state=getattr(status, "state", "?"),
                            bootstrap=getattr(status, "bootstrap", "?"),
                            tripwire=getattr(status, "tripwire_fired", None))
        return KeystationLicense(ks, status, key_map=self._key_map, diag=self._diag)

    def session(self):
        """Context manager the test/run runner wraps a run in (snapshot pinned, A6
        issuer notice once). No-op when the SDK is unavailable."""
        ks = self._sdk()
        if ks is None:
            return nullcontext()
        try:
            return ks.session()
        except Exception:  # noqa: BLE001
            return nullcontext()

    # ---- activation surface (Settings → License) ---------------------------

    def status_payload(self) -> dict:
        """UI-facing status: provider + the raw Keystation status fields."""
        ks = self._sdk()
        if ks is None:
            return {"provider": "keystation", "available": False,
                    "detail": "keystation SDK / core DLL not available"}
        try:
            s = ks.status()
        except Exception as exc:  # noqa: BLE001
            return {"provider": "keystation", "available": False, "detail": str(exc)}
        return {"provider": "keystation", "available": True,
                "state": s.state, "bootstrap": s.bootstrap,
                "tripwire_fired": s.tripwire_fired, "key_tier": s.key_tier,
                "has_lease": s.has_lease,
                "licensed": s.bootstrap == "ACTIVE" and s.state in _VALID_STATES}

    def make_request(self, product_id: str, runtime: str = "python_framework") -> dict:
        """Airgap step 1: emit a device-signed `.ksreq` activation request."""
        ks = self._sdk()
        if ks is None:
            raise RuntimeError("keystation SDK unavailable")
        return ks.make_request(product_id, runtime)

    def activate(self, lease_bundle_path: str) -> None:
        """Ingest a `.kslease` (online Path A or airgap Path B) → ACTIVE."""
        ks = self._sdk()
        if ks is None:
            raise RuntimeError("keystation SDK unavailable")
        ks.activate(lease_bundle_path)

    def ingest_manifest(self, bundle_path: str) -> dict:
        """Verify a signed `.ksupdate` manifest through the core (cert chain →
        embedded root; build_timestamp window) and advance the anti-rollback
        tripwire, then return the parsed manifest. Raises on a bad signature."""
        import json
        ks = self._sdk()
        if ks is None:
            raise RuntimeError("keystation SDK unavailable")
        ks.ingest_manifest(bundle_path)                 # verify + advance tripwire
        bundle = json.loads(pathlib.Path(bundle_path).read_text(encoding="utf-8"))
        return {**bundle.get("manifest", {}), "verified": True}


def build_licensing(app_cfg: dict, config, diag=None):
    """Select the licensing provider from config (secure-distribution P1).

    `app.json` → `licensing: {provider: "stub" | "keystation", key_map: {...}}`.
    Default is `stub` (the pre-integration behavior — a signed path-based license.json),
    so existing deployments are unchanged until they opt in to Keystation. The returned
    object exposes `load_and_verify(license_path)` and `session()`.
    """
    from core.services.licensing import Licensing  # local import avoids any cycle

    lic_cfg = app_cfg.get("licensing") or {}
    provider = lic_cfg.get("provider", "stub")
    if provider == "keystation":
        if diag:
            diag.info("licensing", "provider selected", provider="keystation")
        return KeystationLicensing(diag, key_map=lic_cfg.get("key_map"),
                                   core_lib=lic_cfg.get("core_lib"))
    return Licensing(config, diag)
