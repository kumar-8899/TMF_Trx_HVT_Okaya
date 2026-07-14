"""Licensing — the entitlement source the activation gate reads (CORE.md §3.3, §4).

P3 stub: loads + schema-validates license.json and checks expiry. Signature
verification is stubbed (accepted) and hardened later — this is the "everything
on" starting point PRINCIPLES §3 allows. The gate treats absent entitlements as
OFF (fail-closed).

This becomes the Licensing *module* later; the contract below is what the gate
depends on, so the swap is invisible to the gate.
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.services.config import ConfigService
from core.services.diagnostics import Diagnostics


class License:
    def __init__(self, raw: dict, *, valid: bool, reason: str = "") -> None:
        self.raw = raw
        self.valid = valid
        self.reason = reason
        self._ent = raw.get("entitlements", {}) if valid else {}

    @property
    def plan(self) -> str:
        return self.raw.get("plan", "unknown")

    def allows_module(self, module_id: str) -> bool:
        return bool(self._ent.get("modules", {}).get(module_id, False))

    def allows_variant(self, module_id: str, variant_id: str) -> bool:
        # A per-module variant allow-list is optional. If present it restricts;
        # if absent, the module-level gate already decided (so allow).
        allowed = self._ent.get("variants", {}).get(module_id)
        if allowed is None:
            return True
        return variant_id in allowed

    def allows_feature(self, key: str) -> bool:
        return bool(self._ent.get("features", {}).get(key, False))


class Licensing:
    def __init__(self, config: ConfigService, diag: Diagnostics | None = None) -> None:
        self._config = config
        self._diag = diag

    def session(self):
        """Symmetry with the Keystation provider (the run runner wraps a run in the
        provider's session). The stub has no snapshot to pin ⇒ a no-op context."""
        from contextlib import nullcontext
        return nullcontext()

    def status_payload(self) -> dict:
        """UI-facing status (symmetry with the Keystation provider)."""
        return {"provider": "stub", "available": True,
                "detail": "path-based license.json (signature verification stubbed)"}

    def ingest_manifest(self, bundle_path: str) -> dict:
        """Parse an update manifest WITHOUT signature verification (the stub has no
        trust root). Returns the manifest flagged unverified — the resolver still
        records the offer, but the UI shows it as untrusted."""
        import json
        from pathlib import Path
        bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
        return {**bundle.get("manifest", {}), "verified": False}

    def load_and_verify(self, license_path: str | None) -> License:
        try:
            raw = self._config.load_license(license_path)
        except Exception as exc:  # noqa: BLE001 — fail-closed: no license -> nothing licensed
            if self._diag:
                self._diag.error("licensing", "license load failed", error=str(exc))
            return License({}, valid=False, reason=f"load failed: {exc}")

        # Expiry (signature verification is stubbed in P3).
        try:
            expires = datetime.fromisoformat(raw["expires"].replace("Z", "+00:00"))
            if expires < datetime.now(timezone.utc):
                if self._diag:
                    self._diag.error("licensing", "license expired", expires=raw["expires"])
                return License(raw, valid=False, reason="expired")
        except (KeyError, ValueError) as exc:
            return License(raw, valid=False, reason=f"bad expiry: {exc}")

        if self._diag:
            self._diag.info("licensing", "license ok", plan=raw.get("plan"))
        return License(raw, valid=True)
