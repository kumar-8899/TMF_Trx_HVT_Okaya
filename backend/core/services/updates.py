"""Signed code updates — the station side (secure distribution P3).

Keystation's release model is three tracks under one signed-manifest trust chain
(core DLL · framework · app; chat #4). The station's job here is intake + trust +
resolve + operator-gate — NOT self-mutation: a running Nuitka binary cannot replace
its own file, so *applying* an update is a launcher/restart step. This service:

  1. **ingest** a `.ksupdate` — verify it through the licensing core
     (`licensing.ingest_manifest`: cert chain → embedded root, build_timestamp
     window, anti-rollback tripwire) and record the offered release.
  2. **resolve** applicability against what this station runs (framework version,
     track, ABI floor) — publish ≠ deploy.
  3. **apply** = record operator intent + stage the pointer; the launcher swaps the
     artifact / core DLL on next start (honoring abi_version / pin mode).

Offers + apply-intents are DB records (type `update_offer`), so the whole history
is auditable and survives restart.
"""

from __future__ import annotations

import time

_OFFER = "update_offer"


def _semver(v: str | None) -> tuple:
    try:
        return tuple(int(x) for x in str(v).split(".")[:3])
    except (ValueError, AttributeError):
        return (0, 0, 0)


class UpdateService:
    """Depends on `core.db` (offer records) + `core.licensing` (verify) +
    `core.diag`. `current_version` is the running framework version (core.__version__);
    `current_abi` is the core ABI the framework was built against (-1 = unknown)."""

    def __init__(self, db, licensing, diag, *, current_version: str, current_abi: int = -1):
        self._db = db
        self._lic = licensing
        self._diag = diag
        self._version = current_version
        self._abi = current_abi

    # ---- resolve (publish != deploy) --------------------------------------

    def resolve(self, manifest: dict) -> dict:
        """Applicability verdict for THIS station. Never mutates."""
        track = manifest.get("track")
        offered = manifest.get("version")
        if track not in ("framework", "app"):
            return {"applicable": False, "reason": f"track '{track}' is not station-applicable here"}
        if not manifest.get("verified", False):
            return {"applicable": False, "reason": "manifest signature not verified (untrusted provider)"}
        if _semver(offered) <= _semver(self._version):
            return {"applicable": False,
                    "reason": f"offered {offered} not newer than installed {self._version}"}
        need_abi = manifest.get("min_abi_required", -1)
        if self._abi >= 0 and need_abi is not None and need_abi > self._abi:
            return {"applicable": False,
                    "reason": f"needs core ABI ≥ {need_abi}; station core ABI is {self._abi} — "
                              "update the core DLL first"}
        crit = manifest.get("criticality")
        return {"applicable": True,
                "reason": f"{track} {offered} > {self._version}"
                          + (f" · {crit}" if crit else "")}

    # ---- ingest a .ksupdate -----------------------------------------------

    async def ingest(self, bundle_path: str) -> dict:
        """Verify + record an offered update. Verification (and the anti-rollback
        tripwire advance) happens in the licensing core; a bad signature raises."""
        manifest = self._lic.ingest_manifest(bundle_path)   # verify + tripwire; raises on bad sig
        verdict = self.resolve(manifest)
        rec = {
            "release_id": manifest.get("release_id") or f"rel-{int(time.time())}",
            "track": manifest.get("track"),
            "version": manifest.get("version"),
            "channel": manifest.get("channel"),
            "criticality": manifest.get("criticality"),
            "full_artifact_hash": manifest.get("full_artifact_hash"),
            "build_timestamp": manifest.get("build_timestamp"),
            "min_abi_required": manifest.get("min_abi_required"),
            "verified": manifest.get("verified", False),
            "verdict": verdict,
            "status": "offered",
            "ingested_ts": time.time(),
        }
        await self._db.repo.put(_OFFER, rec, id=rec["release_id"],
                                summary=f"{rec['track']} {rec['version']}")
        self._diag.info("updates", "update offered", release_id=rec["release_id"],
                        track=rec["track"], version=rec["version"],
                        applicable=verdict["applicable"])
        return rec

    async def list_offers(self) -> list[dict]:
        rows = await self._db.repo.query(_OFFER)
        offers = [r["data"] for r in rows]
        offers.sort(key=lambda o: o.get("ingested_ts", 0), reverse=True)
        return offers

    async def apply(self, release_id: str) -> dict:
        """Operator-gated. Records apply intent; the physical swap is the launcher's
        job on next start (a running binary can't replace itself)."""
        rec = await self._db.repo.get(_OFFER, release_id)
        if rec is None:
            raise KeyError(f"no offered update '{release_id}'")
        offer = rec["data"]
        if not offer.get("verdict", {}).get("applicable"):
            raise ValueError(f"update not applicable: {offer.get('verdict', {}).get('reason')}")
        offer["status"] = "apply_pending"
        offer["apply_requested_ts"] = time.time()
        await self._db.repo.put(_OFFER, offer, id=release_id,
                                summary=f"{offer['track']} {offer['version']} (apply pending)")
        self._diag.warning("updates", "update apply requested", release_id=release_id,
                           version=offer.get("version"))
        return {"ok": True, "release_id": release_id, "status": "apply_pending",
                "note": "staged — restart the station via the launcher to apply the new artifact"}

    def current(self) -> dict:
        return {"version": self._version, "abi": self._abi}
