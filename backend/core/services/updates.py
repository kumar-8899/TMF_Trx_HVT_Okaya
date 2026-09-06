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

import hashlib
import time

_OFFER = "update_offer"


class AmcRequired(Exception):
    """Download blocked because the AMC does not cover this build (UPDATES.md §8 → 402)."""


def _asset_bytes(asset: dict, token: str | None) -> bytes:
    """Download one GitHub Release asset's bytes (private-repo needs the API url +
    octet-stream Accept)."""
    import urllib.request
    dl = {"User-Agent": "tmf-station", "Accept": "application/octet-stream"}
    url = asset["url"] if token else asset["browser_download_url"]
    if token:
        dl["Authorization"] = f"Bearer {token}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=dl), timeout=180).read()


def _semver(v: str | None) -> tuple:
    try:
        return tuple(int(x) for x in str(v).split(".")[:3])
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _tag_version(tag: str | None) -> str | None:
    """A GitHub release tag IS the version, modulo the `app-v`/`v` prefix (UPDATES.md §10.3)."""
    if not tag:
        return None
    for prefix in ("app-v", "v"):
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return tag


class UpdateService:
    """Depends on `core.db` (offer records) + `core.licensing` (verify) +
    `core.diag`. `current_version` is the running framework version (core.__version__);
    `current_abi` is the core ABI the framework was built against (-1 = unknown)."""

    def __init__(self, db, licensing, diag, *, current_version: str, current_abi: int = -1,
                 data_dir=None, current_app_version: str | None = None,
                 allow_unverified: bool = False):
        self._db = db
        self._lic = licensing
        self._diag = diag
        self._version = current_version              # framework version (core.__version__)
        self._app_version = current_app_version       # this app's own version (None on framework)
        self._abi = current_abi
        self._data_dir = data_dir   # where the launcher reads relaunch.json
        # Pre-Keystation / internal: install UNSIGNED (stub-provider) offers, still flagged
        # untrusted. Config-gated (app.json updates.allow_unverified); default off so a real
        # Keystation deployment only ever installs a verified manifest (UPDATES.md §trust).
        self._allow_unverified = bool(allow_unverified)

    # ---- resolve (publish != deploy) --------------------------------------

    def resolve(self, manifest: dict) -> dict:
        """Applicability verdict for THIS station. Never mutates."""
        track = manifest.get("track")
        offered = manifest.get("version")
        if track not in ("framework", "app"):
            return {"applicable": False, "reason": f"track '{track}' is not station-applicable here"}
        verified = bool(manifest.get("verified", False))
        if not verified and not self._allow_unverified:
            return {"applicable": False, "reason": "manifest signature not verified (untrusted provider)"}
        # Compare like with like: an app-track update against the app's own version, a
        # framework-track update against the framework version (TEMPLATE.md two-tier).
        baseline = self._app_version if (track == "app" and self._app_version) else self._version
        if _semver(offered) <= _semver(baseline):
            return {"applicable": False,
                    "reason": f"offered {offered} not newer than installed {baseline}"}
        need_abi = manifest.get("min_abi_required", -1)
        if self._abi >= 0 and need_abi is not None and need_abi > self._abi:
            return {"applicable": False,
                    "reason": f"needs core ABI ≥ {need_abi}; station core ABI is {self._abi} — "
                              "update the core DLL first"}
        crit = manifest.get("criticality")
        untrusted = " · UNTRUSTED (unsigned; allow_unverified)" if not verified else ""
        return {"applicable": True, "untrusted": not verified,
                "reason": f"{track} {offered} > {self._version}"
                          + (f" · {crit}" if crit else "") + untrusted}

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

    # ---- GitHub discovery (notify) + download (fetch) ---------------------

    @staticmethod
    def _gh_release(repo: str, token: str | None, *, channel: str = "stable") -> dict:
        """Latest GitHub Release JSON. `stable` uses /releases/latest (excludes
        prereleases); `beta` takes the newest entry regardless of the prerelease flag."""
        import json as _json
        import urllib.request
        h = {"User-Agent": "tmf-station", "Accept": "application/vnd.github+json"}
        if token:
            h["Authorization"] = f"Bearer {token}"

        def _get(path):
            return _json.loads(urllib.request.urlopen(
                urllib.request.Request(f"https://api.github.com/repos/{repo}{path}", headers=h),
                timeout=20).read())

        if channel == "beta":
            rels = _get("/releases")
            return rels[0] if rels else {}
        return _get("/releases/latest")

    async def check(self, repo: str, token: str | None = None, *, channel: str = "stable") -> dict:
        """Discovery — NOTIFY ONLY (UPDATES.md item 5). Polls GitHub, downloads nothing.
        Returns the available release's metadata (or null). Idempotent, network-tolerant."""
        import asyncio
        try:
            rel = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self._gh_release(repo, token, channel=channel))
        except Exception as exc:  # noqa: BLE001 — no network still boots + runs (UPDATES.md §3.1)
            self._diag.warning("updates", "update check failed (no network?)", repo=repo, error=str(exc))
            return {"checked_at": time.time(), "current": self.current(), "available": None,
                    "error": str(exc)}
        asset = next((a for a in rel.get("assets", []) if a["name"].endswith(".ksupdate")), None)
        available = None
        if asset is not None:
            # Gate discovery on version too — an asset existing on the latest release says nothing
            # about whether that release is actually NEWER than what's installed (a repod's own
            # current release always carries a .ksupdate). Cheap: the tag_name IS the version,
            # no manifest fetch needed. Mirrors resolve()'s baseline; an app-track station's own
            # repo only ever carries its own app-track releases, so there's no track ambiguity here.
            baseline = self._app_version or self._version
            offered = _tag_version(rel.get("tag_name"))
            if _semver(offered) > _semver(baseline):
                available = {"tag": rel.get("tag_name"), "published_at": rel.get("published_at"),
                             "notes": rel.get("body"), "asset_name": asset["name"],
                             "asset_bytes": asset.get("size"), "prerelease": rel.get("prerelease")}
            else:
                self._diag.info("updates", "update check: already current",
                                offered=offered, baseline=baseline)
        self._diag.info("updates", "update check", repo=repo, available=bool(available))
        return {"checked_at": time.time(), "current": self.current(), "available": available}

    async def download(self, repo: str, token: str | None = None, *, channel: str = "stable") -> dict:
        """Fetch the latest `.ksupdate`, verify + offer (item 6). **Idempotent on the
        bundle SHA-256**: a bundle already ingested returns the existing offer and does
        NOT advance the anti-rollback tripwire a second time."""
        import asyncio
        from pathlib import Path

        def _fetch() -> tuple[dict, str, bytes]:
            rel = self._gh_release(repo, token, channel=channel)
            asset = next((a for a in rel.get("assets", []) if a["name"].endswith(".ksupdate")), None)
            if asset is None:
                raise RuntimeError(f"no .ksupdate asset in {repo} {rel.get('tag_name')}")
            return rel, asset["name"], _asset_bytes(asset, token)

        rel, name, data = await asyncio.get_running_loop().run_in_executor(None, _fetch)
        tag = rel.get("tag_name", "?")
        sha = hashlib.sha256(data).hexdigest()
        prior = next((o for o in await self.list_offers() if o.get("bundle_sha256") == sha), None)
        if prior is not None:
            self._diag.info("updates", "download idempotent — bundle already ingested",
                            repo=repo, sha=sha[:12], release_id=prior.get("release_id"))
            return {"source": repo, "release": tag, "idempotent": True, **prior}

        dest = Path(self._data_dir or ".") / "updates"
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / name
        path.write_bytes(data)
        try:
            rec = await self.ingest(str(path))           # verify + tripwire advance (once)
        except Exception as exc:  # noqa: BLE001 — VERIFY_FAILED is terminal (UPDATES.md §0)
            bad = {"release_id": f"badsig-{sha[:12]}", "status": "verify_failed",
                   "bundle_sha256": sha, "error": str(exc), "ingested_ts": time.time()}
            await self._db.repo.put(_OFFER, bad, id=bad["release_id"], summary="verify failed")
            self._diag.error("updates", "update verify FAILED (terminal)", repo=repo, error=str(exc))
            raise
        rec["bundle_sha256"] = sha
        # AMC gate (UPDATES.md §8): may this station install a build with THIS
        # build_timestamp? Keystation-only; the stub provider has no gate (dev allows).
        reason = getattr(self._lic, "amc_gate", lambda _ts: None)(rec.get("build_timestamp"))
        if reason:
            rec["status"] = "amc_blocked"
            rec["amc_reason"] = reason
            await self._db.repo.put(_OFFER, rec, id=rec["release_id"],
                                    summary=f"{rec['track']} {rec['version']} (AMC required)")
            self._diag.warning("updates", "download blocked by AMC", release_id=rec["release_id"],
                               reason=reason)
            raise AmcRequired(reason)
        # Materialize the real artifact (a separate .zip Release asset) → a staged
        # run.dist the launcher can swap. Verify sha == full_artifact_hash first.
        rec["staged_dir"] = await asyncio.get_running_loop().run_in_executor(
            None, lambda: self._materialize(rel, rec, token))
        rec["status"] = "downloaded"
        await self._db.repo.put(_OFFER, rec, id=rec["release_id"],
                                summary=f"{rec['track']} {rec['version']} (downloaded)")
        return {"source": repo, "release": tag, "idempotent": False, **rec}

    def _materialize(self, rel: dict, offer: dict, token: str | None) -> str | None:
        """Fetch the artifact zip (GitHub), then stage it. Returns the staged path, or None
        when there's no zip asset (dev / a trust-only release) — the launcher then no-ops."""
        zip_asset = next((a for a in rel.get("assets", []) if a["name"].endswith(".zip")), None)
        if zip_asset is None:
            self._diag.warning("updates", "no artifact zip asset — offer not stageable",
                               release_id=offer.get("release_id"))
            return None
        return self._stage_zip_bytes(_asset_bytes(zip_asset, token), offer)

    def _stage_zip_bytes(self, data: bytes, offer: dict) -> str:
        """Verify sha256 == full_artifact_hash, then unpack the artifact zip to a staged
        run.dist the launcher can swap. Shared by the GitHub path (_materialize) and the
        local-file path (install_from_file) — only the SOURCE of `data` differs, so hash
        verification + swap/rollback semantics stay identical (UPDATES.md / DEPLOY_STATION §E-bis)."""
        import io
        import shutil
        import zipfile
        from pathlib import Path
        sha = hashlib.sha256(data).hexdigest()
        want = offer.get("full_artifact_hash")
        if want and sha != want:
            raise RuntimeError(f"artifact hash mismatch: got {sha[:12]}… want {want[:12]}…")
        staged = Path(self._data_dir or ".") / "updates" / "staged" / "run.dist"
        if staged.exists():
            shutil.rmtree(staged)
        staged.mkdir(parents=True)
        zipfile.ZipFile(io.BytesIO(data)).extractall(staged)
        self._diag.info("updates", "artifact staged", release_id=offer.get("release_id"), dir=str(staged))
        return str(staged)

    # ---- local-file (air-gapped / USB) install ----------------------------

    async def install_from_file(self, ksupdate_path: str, zip_path: str) -> dict:
        """Air-gapped install (UPDATES.md §E-bis): run the SAME verify + stage pipeline as the
        online `download()`, but read the `.ksupdate` (trust) and `.zip` (artifact) from LOCAL
        paths (USB) instead of GitHub. Hash verification against the signed manifest and the
        launcher's swap/rollback are IDENTICAL to the online path — only the source differs, so a
        bench with no internet updates through the normal Updates flow. Caller then Installs +
        Relaunches the staged offer exactly as with an online download."""
        import asyncio
        from pathlib import Path
        if not Path(ksupdate_path).is_file():
            raise FileNotFoundError(f"no .ksupdate at {ksupdate_path}")
        if not Path(zip_path).is_file():
            raise FileNotFoundError(f"no artifact .zip at {zip_path}")
        rec = await self.ingest(ksupdate_path)      # verify + tripwire advance + record offer
        rec["bundle_sha256"] = hashlib.sha256(Path(ksupdate_path).read_bytes()).hexdigest()
        if not rec.get("verdict", {}).get("applicable"):
            await self._db.repo.put(_OFFER, rec, id=rec["release_id"],
                                    summary=f"{rec['track']} {rec['version']} (offered from file)")
            return {"source": "file", "idempotent": False, **rec}   # surfaced, not stageable
        # AMC gate — same as the online download (Keystation-only; stub allows).
        reason = getattr(self._lic, "amc_gate", lambda _ts: None)(rec.get("build_timestamp"))
        if reason:
            rec["status"] = "amc_blocked"
            rec["amc_reason"] = reason
            await self._db.repo.put(_OFFER, rec, id=rec["release_id"],
                                    summary=f"{rec['track']} {rec['version']} (AMC required)")
            raise AmcRequired(reason)
        data = Path(zip_path).read_bytes()
        rec["staged_dir"] = await asyncio.get_running_loop().run_in_executor(
            None, lambda: self._stage_zip_bytes(data, rec))
        rec["status"] = "downloaded"
        await self._db.repo.put(_OFFER, rec, id=rec["release_id"],
                                summary=f"{rec['track']} {rec['version']} (staged from file)")
        self._diag.info("updates", "update staged from local file", release_id=rec["release_id"],
                        version=rec.get("version"))
        return {"source": "file", "idempotent": False, **rec}

    # back-compat alias
    async def check_github(self, repo: str, token: str | None = None) -> dict:
        return await self.download(repo, token)

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

    async def request_relaunch(self, release_id: str) -> dict:
        """Operator clicked 'Relaunch to update'. Write the launcher marker
        (data/relaunch.json) so the supervisor swaps the staged artifact on the next
        start; the caller then exits the process with the RELAUNCH code (42)."""
        import json
        from pathlib import Path
        rec = await self._db.repo.get(_OFFER, release_id)
        if rec is None:
            raise KeyError(f"no offered update '{release_id}'")
        offer = rec["data"]
        if not offer.get("verdict", {}).get("applicable"):
            raise ValueError("update not applicable")
        marker = {
            "release_id": release_id,
            "version": offer.get("version"),
            "staged_dir": offer.get("staged_dir"),         # None in dev → launcher restarts only
            "expected_hash": offer.get("full_artifact_hash"),
            "requested_ts": time.time(),
        }
        if self._data_dir is not None:
            d = Path(self._data_dir)
            d.mkdir(parents=True, exist_ok=True)
            (d / "relaunch.json").write_text(json.dumps(marker, indent=2), encoding="utf-8")
        offer["status"] = "relaunch_requested"
        await self._db.repo.put(_OFFER, offer, id=release_id,
                                summary=f"{offer['track']} {offer['version']} (relaunch requested)")
        self._diag.warning("updates", "relaunch requested", release_id=release_id,
                           version=offer.get("version"))
        return marker

    def current(self) -> dict:
        return {"version": self._version, "app_version": self._app_version, "abi": self._abi}

    # ---- rollback + status (UPDATES.md items 7, 9) ------------------------

    def _read_backups(self) -> tuple[list[dict], str | None]:
        """Backup metadata sidecars + the last-known-good id (written by launcher.py)."""
        import json
        from pathlib import Path
        if self._data_dir is None:
            return [], None
        root = Path(self._data_dir)
        lkg = None
        try:
            lkg = json.loads((root / "last_known_good.json").read_text(encoding="utf-8")).get("backup_id")
        except (OSError, json.JSONDecodeError):
            pass
        out = []
        for meta in sorted((root / "backups").glob("bak-*/meta.json"), reverse=True):
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            m["last_known_good"] = (m.get("backup_id") == lkg)
            out.append(m)
        return out, lkg

    async def rollback(self, target: str = "last_known_good") -> dict:
        """Write a rollback marker; the caller exits 42 and the launcher swaps the backup
        (binary + DB snapshot) back in. Reverting to a LOCAL backup does NOT re-ingest, so
        it **bypasses the anti-rollback tripwire** — that artifact was verified when first
        installed (UPDATES.md §5.4)."""
        import json
        from pathlib import Path
        backups, lkg = self._read_backups()
        want = lkg if target == "last_known_good" else target
        if not want or (target != "last_known_good" and want not in {b.get("backup_id") for b in backups}):
            raise KeyError(f"no rollback target '{target}'")
        marker = {"rollback": want, "requested_ts": time.time()}
        if self._data_dir is not None:
            d = Path(self._data_dir)
            d.mkdir(parents=True, exist_ok=True)
            (d / "relaunch.json").write_text(json.dumps(marker, indent=2), encoding="utf-8")
        self._diag.warning("updates", "rollback requested", target=want)
        return marker

    def _swap_error(self) -> dict | None:
        """The launcher's breadcrumb from a swap that failed on relaunch (data/last_swap_error.json).
        A failed swap leaves the OLD build live and the launcher silently relaunches it, so the
        offer status stays `relaunch_requested` forever — this is how the operator finds out."""
        import json
        from pathlib import Path
        if self._data_dir is None:
            return None
        try:
            e = json.loads((Path(self._data_dir) / "last_swap_error.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return {"version": e.get("version"), "error": e.get("error"),
                "strikes": e.get("strikes", 1), "at": e.get("at")}

    async def status(self) -> dict:
        backups, lkg = self._read_backups()
        offers = await self.list_offers()
        swap_error = self._swap_error()
        state = offers[0]["status"] if offers else "none"
        if swap_error and state == "relaunch_requested":
            state = "swap_failed"
        return {"current": self.current(),
                "state": state,
                "swap_error": swap_error,
                "last_known_good": lkg,
                "backups": [{"id": b.get("backup_id"), "version": b.get("version"),
                             "installed_at": b.get("installed_at"),
                             "last_known_good": b.get("last_known_good", False)} for b in backups]}
