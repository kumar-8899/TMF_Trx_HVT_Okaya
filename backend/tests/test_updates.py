"""Signed code updates — the station side (secure-distribution P3).

Exercises the resolver + ingest/apply lifecycle with a fake licensing provider and
an in-memory DB. The real signature verification lives in the Keystation core and is
proven by the SDK e2e; here we prove the station's publish!=deploy policy.
"""

import pytest

from core.services.db import Database
from core.services.diagnostics import Diagnostics
from core.services.updates import UpdateService


class _FakeLicensing:
    """Returns the manifest the caller pre-seeded; `verified` flags trust."""

    def __init__(self, manifest):
        self._m = manifest

    def ingest_manifest(self, bundle_path):
        if self._m is None:
            raise RuntimeError("bad signature")
        return dict(self._m)


def _manifest(track="framework", version="1.1.0", verified=True, min_abi=1, crit="recommended"):
    return {"release_id": f"rel-{version}", "track": track, "version": version,
            "channel": "stable", "criticality": crit, "min_abi_required": min_abi,
            "full_artifact_hash": "abc", "build_timestamp": 1_700_000_000,
            "verified": verified}


async def _svc(manifest, *, version="1.0.0", abi=-1):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    diag = Diagnostics("st1", "0.0.0", sinks=[lambda e: None])
    return UpdateService(db, _FakeLicensing(manifest), diag,
                         current_version=version, current_abi=abi), db


async def test_resolve_newer_framework_is_applicable():
    svc, db = await _svc(_manifest(version="1.1.0"))
    v = svc.resolve(_manifest(version="1.1.0"))
    assert v["applicable"] is True
    await db.close()


async def test_resolve_older_or_equal_rejected():
    svc, db = await _svc(_manifest(version="1.0.0"))
    assert svc.resolve(_manifest(version="1.0.0"))["applicable"] is False
    assert svc.resolve(_manifest(version="0.9.0"))["applicable"] is False
    await db.close()


async def test_resolve_unverified_rejected():
    svc, db = await _svc(_manifest(verified=False))
    assert svc.resolve(_manifest(verified=False))["applicable"] is False
    await db.close()


async def test_resolve_abi_floor_blocks():
    svc, db = await _svc(_manifest(version="2.0.0", min_abi=3), abi=1)
    v = svc.resolve(_manifest(version="2.0.0", min_abi=3))
    assert v["applicable"] is False and "ABI" in v["reason"]
    await db.close()


async def test_resolve_app_track_applicable():
    svc, db = await _svc(_manifest(track="app", version="1.1.0"))
    assert svc.resolve(_manifest(track="app", version="1.1.0"))["applicable"] is True
    await db.close()


async def test_resolve_compares_by_track_two_tier():
    # framework 1.9.0, app 1.0.0 (independent). An app-track 1.0.1 is applicable (newer than
    # the APP), even though 1.0.1 < the framework version; framework-track compares framework.
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    diag = Diagnostics("st1", "0.0.0", sinks=[lambda e: None])
    svc = UpdateService(db, _FakeLicensing(_manifest()), diag,
                        current_version="1.9.0", current_app_version="1.0.0")
    assert svc.resolve(_manifest(track="app", version="1.0.1"))["applicable"] is True
    assert svc.resolve(_manifest(track="app", version="1.0.0"))["applicable"] is False
    assert svc.resolve(_manifest(track="framework", version="1.9.1"))["applicable"] is True
    assert svc.resolve(_manifest(track="framework", version="1.9.0"))["applicable"] is False
    assert svc.current()["app_version"] == "1.0.0"
    await db.close()


async def test_resolve_core_track_not_station_applicable():
    svc, db = await _svc(_manifest(track="core"))
    assert svc.resolve(_manifest(track="core"))["applicable"] is False
    await db.close()


async def test_ingest_records_offer_then_apply():
    svc, db = await _svc(_manifest(version="1.2.0"))
    rec = await svc.ingest("dummy.ksupdate")
    assert rec["verdict"]["applicable"] is True and rec["status"] == "offered"
    offers = await svc.list_offers()
    assert len(offers) == 1 and offers[0]["version"] == "1.2.0"
    res = await svc.apply(rec["release_id"])
    assert res["status"] == "apply_pending"
    assert (await svc.list_offers())[0]["status"] == "apply_pending"
    await db.close()


async def test_request_relaunch_writes_marker(tmp_path):
    svc, db = await _svc(_manifest(version="1.3.0"))
    svc._data_dir = tmp_path
    rec = await svc.ingest("dummy.ksupdate")
    await svc.apply(rec["release_id"])
    marker = await svc.request_relaunch(rec["release_id"])
    assert marker["version"] == "1.3.0"
    import json
    written = json.loads((tmp_path / "relaunch.json").read_text())
    assert written["release_id"] == rec["release_id"]
    assert (await svc.list_offers())[0]["status"] == "relaunch_requested"
    await db.close()


async def test_apply_rejects_inapplicable():
    svc, db = await _svc(_manifest(version="0.9.0"))
    rec = await svc.ingest("dummy.ksupdate")
    assert rec["verdict"]["applicable"] is False
    with pytest.raises(ValueError):
        await svc.apply(rec["release_id"])
    await db.close()


async def test_ingest_bad_signature_raises():
    svc, db = await _svc(None)
    with pytest.raises(RuntimeError):
        await svc.ingest("tampered.ksupdate")
    await db.close()


# --- Phase 2: discovery (notify) + download (fetch, idempotent) -------------

class _Resp:
    def __init__(self, b):
        self._b = b

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _gh(assets=True):
    a = [{"name": "app-1.2.0.ksupdate", "url": "http://x/api", "browser_download_url": "http://x/dl",
          "size": 42}] if assets else []
    return {"tag_name": "v1.2.0", "published_at": "t0", "body": "notes", "prerelease": False, "assets": a}


async def test_check_is_notify_only(monkeypatch):
    svc, db = await _svc(_manifest(version="1.2.0"))
    monkeypatch.setattr(UpdateService, "_gh_release", staticmethod(lambda *a, **k: _gh()))
    r = await svc.check("owner/repo")
    assert r["available"]["asset_name"] == "app-1.2.0.ksupdate"
    assert r["available"]["tag"] == "v1.2.0"
    assert await svc.list_offers() == []          # NOTHING downloaded/ingested
    await db.close()


async def test_check_none_when_no_asset(monkeypatch):
    svc, db = await _svc(_manifest())
    monkeypatch.setattr(UpdateService, "_gh_release", staticmethod(lambda *a, **k: _gh(assets=False)))
    assert (await svc.check("owner/repo"))["available"] is None
    await db.close()


class _CountLic:
    def __init__(self, manifest):
        self._m = manifest
        self.calls = 0

    def ingest_manifest(self, path):
        self.calls += 1
        if self._m is None:
            raise RuntimeError("bad signature")
        return dict(self._m)


async def _svc_lic(lic, *, version="1.0.0", tmp=None):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    diag = Diagnostics("st1", "0.0.0", sinks=[lambda e: None])
    svc = UpdateService(db, lic, diag, current_version=version, data_dir=tmp)
    return svc, db


async def test_download_idempotent_no_double_tripwire(monkeypatch, tmp_path):
    import urllib.request
    lic = _CountLic(_manifest(version="1.2.0"))
    svc, db = await _svc_lic(lic, tmp=tmp_path)
    monkeypatch.setattr(UpdateService, "_gh_release", staticmethod(lambda *a, **k: _gh()))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp(b"same-bundle-bytes"))
    r1 = await svc.download("owner/repo")
    assert r1["idempotent"] is False and r1["status"] == "downloaded"
    r2 = await svc.download("owner/repo")           # same bytes → idempotent
    assert r2["idempotent"] is True
    assert lic.calls == 1                            # tripwire advanced exactly ONCE
    assert len(await svc.list_offers()) == 1
    await db.close()


async def test_download_verify_failed_is_terminal(monkeypatch, tmp_path):
    import urllib.request
    svc, db = await _svc_lic(_CountLic(None), tmp=tmp_path)   # licensing raises
    monkeypatch.setattr(UpdateService, "_gh_release", staticmethod(lambda *a, **k: _gh()))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp(b"tampered"))
    with pytest.raises(RuntimeError):
        await svc.download("owner/repo")
    offers = await svc.list_offers()
    assert any(o["status"] == "verify_failed" for o in offers)
    await db.close()


# --- Phase 3: rollback + status --------------------------------------------

def _seed_backup(tmp_path, bid, version, *, lkg=False):
    import json
    d = tmp_path / "backups" / bid
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps(
        {"backup_id": bid, "version": version, "installed_at": 1.0}), encoding="utf-8")
    if lkg:
        (tmp_path / "last_known_good.json").write_text(json.dumps({"backup_id": bid}), encoding="utf-8")


async def test_status_lists_backups_and_lkg(tmp_path):
    svc, db = await _svc(_manifest())
    svc._data_dir = tmp_path
    _seed_backup(tmp_path, "bak-1", "1.0.0", lkg=True)
    _seed_backup(tmp_path, "bak-2", "1.1.0")
    st = await svc.status()
    assert st["last_known_good"] == "bak-1"
    by = {b["id"]: b for b in st["backups"]}
    assert by["bak-1"]["last_known_good"] is True and by["bak-2"]["last_known_good"] is False
    await db.close()


async def test_rollback_writes_marker(tmp_path):
    import json
    svc, db = await _svc(_manifest())
    svc._data_dir = tmp_path
    _seed_backup(tmp_path, "bak-1", "1.0.0", lkg=True)
    marker = await svc.rollback("last_known_good")
    assert marker["rollback"] == "bak-1"
    assert json.loads((tmp_path / "relaunch.json").read_text())["rollback"] == "bak-1"
    await db.close()


async def test_rollback_unknown_target_raises(tmp_path):
    svc, db = await _svc(_manifest())
    svc._data_dir = tmp_path
    with pytest.raises(KeyError):
        await svc.rollback("bak-nope")
    await db.close()


# --- Phase 4: AMC gate (build_timestamp vs amc.expires) --------------------

class _AmcLic:
    """Licensing provider with an AMC window ending at `expires` (unix)."""

    def __init__(self, manifest, expires):
        self._m = manifest
        self.expires = expires

    def ingest_manifest(self, path):
        return dict(self._m)

    def amc_gate(self, build_timestamp):
        if build_timestamp is not None and int(build_timestamp) > self.expires:
            return "this update was released after your AMC ended"
        return None


async def test_download_blocked_when_build_after_amc(monkeypatch, tmp_path):
    import urllib.request
    from core.services.updates import AmcRequired
    # manifest build_timestamp = 1_700_000_000; AMC ended earlier → blocked (402)
    svc, db = await _svc_lic(_AmcLic(_manifest(version="1.2.0"), expires=1_600_000_000), tmp=tmp_path)
    monkeypatch.setattr(UpdateService, "_gh_release", staticmethod(lambda *a, **k: _gh()))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp(b"bundle"))
    with pytest.raises(AmcRequired):
        await svc.download("owner/repo")
    assert any(o["status"] == "amc_blocked" for o in await svc.list_offers())
    await db.close()


async def test_download_allowed_within_amc(monkeypatch, tmp_path):
    import urllib.request
    svc, db = await _svc_lic(_AmcLic(_manifest(version="1.2.0"), expires=1_800_000_000), tmp=tmp_path)
    monkeypatch.setattr(UpdateService, "_gh_release", staticmethod(lambda *a, **k: _gh()))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp(b"bundle"))
    r = await svc.download("owner/repo")
    assert r["status"] == "downloaded"                 # build within AMC → allowed
    await db.close()


# --- Phase 5: _materialize (artifact zip → staged run.dist) ----------------

async def test_materialize_unpacks_and_verifies_hash(tmp_path, monkeypatch):
    import hashlib
    import io
    import zipfile
    from pathlib import Path

    from core.services import updates as U
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("run.exe", "BINARY")
        z.writestr("RELEASE.json", '{"version":"1.2.0"}')
    data = buf.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(U, "_asset_bytes", lambda asset, token: data)

    svc, db = await _svc(_manifest())
    svc._data_dir = tmp_path
    rel = {"assets": [{"name": "app-1.2.0.zip", "url": "http://x/z", "browser_download_url": "http://x/z"}]}
    staged = svc._materialize(rel, {"release_id": "r", "full_artifact_hash": sha}, None)
    assert (Path(staged) / "run.exe").read_text() == "BINARY"     # unpacked
    with pytest.raises(RuntimeError):                              # hash mismatch rejected
        svc._materialize(rel, {"release_id": "r2", "full_artifact_hash": "deadbeef"}, None)
    await db.close()
