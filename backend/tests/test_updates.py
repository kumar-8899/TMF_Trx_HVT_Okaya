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


async def _svc(manifest, *, version="1.0.0", abi=-1, station_mode="online"):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    diag = Diagnostics("st1", "0.0.0", sinks=[lambda e: None])
    return UpdateService(db, _FakeLicensing(manifest), diag,
                         current_version=version, current_abi=abi,
                         station_mode=station_mode), db


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


def _gh_tag(tag: str):
    return {"tag_name": tag, "published_at": "t0", "body": "notes", "prerelease": False,
            "assets": [{"name": "app-x.ksupdate", "url": "http://x/api",
                       "browser_download_url": "http://x/dl", "size": 42}]}


async def test_check_no_offer_when_latest_release_is_the_current_version(monkeypatch):
    """The bug: a station on app v1.0.2 checking a repo whose latest release is ALSO app-v1.0.2
    must NOT show "Update available" — check() must compare versions, not just "does an asset exist"."""
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    diag = Diagnostics("st1", "0.0.0", sinks=[lambda e: None])
    svc = UpdateService(db, _FakeLicensing(_manifest()), diag,
                        current_version="1.14.0", current_app_version="1.0.2")
    monkeypatch.setattr(UpdateService, "_gh_release", staticmethod(lambda *a, **k: _gh_tag("app-v1.0.2")))
    r = await svc.check("owner/repo")
    assert r["available"] is None
    await db.close()


async def test_check_no_offer_when_latest_release_is_older(monkeypatch):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    diag = Diagnostics("st1", "0.0.0", sinks=[lambda e: None])
    svc = UpdateService(db, _FakeLicensing(_manifest()), diag,
                        current_version="1.14.0", current_app_version="1.0.2")
    monkeypatch.setattr(UpdateService, "_gh_release", staticmethod(lambda *a, **k: _gh_tag("app-v1.0.1")))
    r = await svc.check("owner/repo")
    assert r["available"] is None
    await db.close()


async def test_check_offers_when_latest_release_is_genuinely_newer(monkeypatch):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    diag = Diagnostics("st1", "0.0.0", sinks=[lambda e: None])
    svc = UpdateService(db, _FakeLicensing(_manifest()), diag,
                        current_version="1.14.0", current_app_version="1.0.2")
    monkeypatch.setattr(UpdateService, "_gh_release", staticmethod(lambda *a, **k: _gh_tag("app-v1.0.3")))
    r = await svc.check("owner/repo")
    assert r["available"] is not None and r["available"]["tag"] == "app-v1.0.3"
    await db.close()


async def test_check_falls_back_to_framework_version_with_no_app_track(monkeypatch):
    """Framework-track station (no app payload): baseline is current_version, plain 'v' tag prefix."""
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    diag = Diagnostics("st1", "0.0.0", sinks=[lambda e: None])
    svc = UpdateService(db, _FakeLicensing(_manifest()), diag, current_version="1.16.1")
    monkeypatch.setattr(UpdateService, "_gh_release", staticmethod(lambda *a, **k: _gh_tag("v1.16.1")))
    assert (await svc.check("owner/repo"))["available"] is None
    monkeypatch.setattr(UpdateService, "_gh_release", staticmethod(lambda *a, **k: _gh_tag("v1.17.0")))
    assert (await svc.check("owner/repo"))["available"] is not None
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


async def test_status_surfaces_launcher_swap_error(tmp_path):
    """A relaunch swap that fails on the station (orphaned controller holding run.dist open,
    say) leaves the offer stuck at `relaunch_requested` forever. The launcher drops
    data/last_swap_error.json; status() turns that into a real `swap_failed` state the
    Updates page can show."""
    import json
    svc, db = await _svc(_manifest(version="1.3.0"))
    svc._data_dir = tmp_path
    rec = await svc.ingest("dummy.ksupdate")
    await svc.apply(rec["release_id"])
    await svc.request_relaunch(rec["release_id"])
    (tmp_path / "last_swap_error.json").write_text(json.dumps(
        {"version": "1.3.0", "error": "[WinError 32] ... 'run.dist'", "strikes": 3, "at": 1.0}),
        encoding="utf-8")
    st = await svc.status()
    assert st["state"] == "swap_failed"
    assert st["swap_error"]["strikes"] == 3 and "WinError 32" in st["swap_error"]["error"]
    await db.close()


async def test_status_has_no_swap_error_when_clean(tmp_path):
    svc, db = await _svc(_manifest())
    svc._data_dir = tmp_path
    st = await svc.status()
    assert st["swap_error"] is None and st["state"] == "none"
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
    result = svc._materialize(rel, {"release_id": "r", "full_artifact_hash": sha}, None)
    assert (Path(result["staged_dir"]) / "run.exe").read_text() == "BINARY"     # unpacked
    with pytest.raises(RuntimeError):                              # hash mismatch rejected
        svc._materialize(rel, {"release_id": "r2", "full_artifact_hash": "deadbeef"}, None)
    await db.close()


# --- Phase 6 (§E-bis): install from local file (air-gapped / USB) -----------

async def test_install_from_file_stages_offline(tmp_path):
    """Local .ksupdate + .zip → same verify + stage as the online path, no network."""
    import hashlib
    import io
    import zipfile
    from pathlib import Path

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("run.exe", "BINARY")
    zdata = buf.getvalue()
    sha = hashlib.sha256(zdata).hexdigest()
    zip_path = tmp_path / "app-1.2.0.zip"
    zip_path.write_bytes(zdata)
    ks_path = tmp_path / "app-1.2.0.ksupdate"
    ks_path.write_text("signed-manifest", encoding="utf-8")

    # manifest's full_artifact_hash must match the local zip so staging verifies.
    man = _manifest(track="app", version="1.2.0")
    man["full_artifact_hash"] = sha
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    diag = Diagnostics("st1", "0.0.0", sinks=[lambda e: None])
    svc = UpdateService(db, _FakeLicensing(man), diag, current_version="1.9.0",
                        current_app_version="1.0.0", data_dir=tmp_path, station_mode="air_gapped")

    rec = await svc.install_from_file(str(ks_path), str(zip_path))
    assert rec["status"] == "downloaded" and rec["source"] == "file"
    assert (Path(rec["staged_dir"]) / "run.exe").read_text() == "BINARY"
    assert (await svc.list_offers())[0]["status"] == "downloaded"
    await db.close()


async def test_install_from_file_hash_mismatch_raises(tmp_path):
    from pathlib import Path
    (tmp_path / "a.zip").write_bytes(b"wrong-bytes")
    (tmp_path / "a.ksupdate").write_text("m", encoding="utf-8")
    man = _manifest(track="app", version="1.2.0")
    man["full_artifact_hash"] = "deadbeef"                 # won't match the zip
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    diag = Diagnostics("st1", "0.0.0", sinks=[lambda e: None])
    svc = UpdateService(db, _FakeLicensing(man), diag, current_version="1.0.0",
                        current_app_version="1.0.0", data_dir=tmp_path, station_mode="air_gapped")
    with pytest.raises(RuntimeError):
        await svc.install_from_file(str(Path(tmp_path) / "a.ksupdate"), str(Path(tmp_path) / "a.zip"))
    await db.close()


async def test_install_from_file_missing_paths_raise(tmp_path):
    svc, db = await _svc(_manifest(), station_mode="air_gapped")
    svc._data_dir = tmp_path
    with pytest.raises(FileNotFoundError):
        await svc.install_from_file(str(tmp_path / "nope.ksupdate"), str(tmp_path / "nope.zip"))
    await db.close()


# --- station_mode: restrict a station to exactly one update channel -------------

async def test_station_mode_defaults_to_online_and_stays_permissive():
    svc, db = await _svc(_manifest())
    assert svc.station_mode == "online"
    svc._require_online()                        # no raise
    from core.services.updates import StationModeBlocked
    with pytest.raises(StationModeBlocked):
        svc._require_air_gapped()               # install-file is the one blocked online
    await db.close()


async def test_air_gapped_station_refuses_online_check_and_download(monkeypatch):
    from core.services.updates import StationModeBlocked
    svc, db = await _svc(_manifest(version="1.2.0"), station_mode="air_gapped")
    # even with a reachable "GitHub", the source gate trips first — no network call is made
    monkeypatch.setattr(UpdateService, "_gh_release",
                        staticmethod(lambda *a, **k: (_ for _ in ()).throw(AssertionError("network hit"))))
    with pytest.raises(StationModeBlocked):
        await svc.check("owner/repo")
    with pytest.raises(StationModeBlocked):
        await svc.download("owner/repo")
    await db.close()


async def test_online_station_refuses_install_from_file(tmp_path):
    from core.services.updates import StationModeBlocked
    (tmp_path / "a.zip").write_bytes(b"z")
    (tmp_path / "a.ksupdate").write_text("m", encoding="utf-8")
    svc, db = await _svc(_manifest(track="app", version="1.2.0"), station_mode="online")
    svc._data_dir = tmp_path
    with pytest.raises(StationModeBlocked):
        await svc.install_from_file(str(tmp_path / "a.ksupdate"), str(tmp_path / "a.zip"))
    await db.close()


async def test_air_gapped_station_allows_install_from_file(tmp_path):
    import hashlib
    import io
    import zipfile
    from pathlib import Path

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("run.exe", "BINARY")
    zdata = buf.getvalue()
    man = _manifest(track="app", version="1.2.0")
    man["full_artifact_hash"] = hashlib.sha256(zdata).hexdigest()
    (tmp_path / "a.zip").write_bytes(zdata)
    (tmp_path / "a.ksupdate").write_text("signed", encoding="utf-8")
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    diag = Diagnostics("st1", "0.0.0", sinks=[lambda e: None])
    svc = UpdateService(db, _FakeLicensing(man), diag, current_version="1.9.0",
                        current_app_version="1.0.0", data_dir=tmp_path, station_mode="air_gapped")
    rec = await svc.install_from_file(str(tmp_path / "a.ksupdate"), str(tmp_path / "a.zip"))
    assert rec["status"] == "downloaded"
    assert (Path(rec["staged_dir"]) / "run.exe").read_text() == "BINARY"
    await db.close()


async def test_unknown_station_mode_falls_back_to_online():
    svc, db = await _svc(_manifest(), station_mode="weird")
    assert svc.station_mode == "online"
    await db.close()


def _zip_bytes(*names: str) -> bytes:
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, "x")
    return buf.getvalue()


async def test_materialize_stages_the_full_run_dist_tree(tmp_path):
    import hashlib

    data = _zip_bytes("run.exe", "RELEASE.json")
    sha = hashlib.sha256(data).hexdigest()

    from core.services import updates as U
    orig = U._asset_bytes
    U._asset_bytes = staticmethod(lambda asset, token: data)
    try:
        svc, db = await _svc(_manifest())
        svc._data_dir = tmp_path
        rel = {"assets": [{"name": "acme-1.2.0.zip", "url": "http://x/full"}]}
        result = svc._materialize(rel, {"release_id": "r", "full_artifact_hash": sha}, None)
        assert result["staged_dir"].endswith("run.dist")
    finally:
        U._asset_bytes = orig
    await db.close()


async def test_stage_zip_bytes_verifies_against_the_one_signed_hash(tmp_path):
    """There is only ONE hash field (full_artifact_hash) — a mismatch is rejected before the
    zip is ever unpacked."""
    svc, db = await _svc(_manifest())
    svc._data_dir = tmp_path
    data = _zip_bytes("run.exe")
    with pytest.raises(RuntimeError):
        svc._stage_zip_bytes(data, {"release_id": "r", "full_artifact_hash": "deadbeef"})
    await db.close()


async def test_request_relaunch_marker_has_no_scope_field(tmp_path):
    """The scope/two-tree update mechanism was retired along with narrow-compile-surface — the
    relaunch marker carries only staged_dir + the one signed hash."""
    svc, db = await _svc(_manifest(version="1.5.0"))
    svc._data_dir = tmp_path
    rec = await svc.ingest("dummy.ksupdate")
    await svc.apply(rec["release_id"])
    marker = await svc.request_relaunch(rec["release_id"])
    assert "scope" not in marker
    assert marker["expected_hash"] == "abc"         # full_artifact_hash
    await db.close()


# --- scan_incoming: fixed-slot convenience over install_from_file (no manual path typing) ------
# deploy/build-update-package.ps1's Inno .exe drops files at this one fixed slot; the operator
# clicks "Scan for updates" instead of browsing to a path.

async def _svc_incoming(manifest, *, version="1.0.0", station_mode="air_gapped"):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    diag = Diagnostics("st1", "0.0.0", sinks=[lambda e: None])
    return UpdateService(db, _FakeLicensing(manifest), diag,
                         current_version=version, station_mode=station_mode), db


def _write_incoming(svc, *, zip_bytes: bytes):
    d = svc.incoming_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "update.ksupdate").write_text("signed", encoding="utf-8")
    (d / "update.zip").write_bytes(zip_bytes)


async def test_scan_incoming_stages_the_incoming_slot_when_present(tmp_path):
    import hashlib

    zip_bytes = _zip_bytes("run.exe")
    manifest = _manifest(track="app", version="2.0.0")
    manifest["full_artifact_hash"] = hashlib.sha256(zip_bytes).hexdigest()
    svc, db = await _svc_incoming(manifest, version="1.9.0")
    svc._data_dir = tmp_path
    _write_incoming(svc, zip_bytes=zip_bytes)

    found = await svc.scan_incoming()

    assert len(found) == 1 and found[0]["version"] == "2.0.0"
    offers = await svc.list_offers()
    assert len(offers) == 1
    await db.close()


async def test_scan_incoming_returns_empty_when_nothing_incoming(tmp_path):
    svc, db = await _svc_incoming(_manifest(track="app", version="2.0.0"), version="1.9.0")
    svc._data_dir = tmp_path
    # incoming/ deliberately left empty

    found = await svc.scan_incoming()

    assert found == []
    await db.close()


async def test_scan_incoming_requires_air_gapped():
    from core.services.updates import StationModeBlocked
    svc, db = await _svc_incoming(_manifest(), station_mode="online")
    with pytest.raises(StationModeBlocked):
        await svc.scan_incoming()
    await db.close()


async def test_scan_incoming_reports_an_error_without_raising(tmp_path):
    manifest = _manifest(track="app", version="2.0.0")
    manifest["full_artifact_hash"] = "deadbeef"           # won't match the zip -> stage raises
    svc, db = await _svc_incoming(manifest, version="1.9.0")
    svc._data_dir = tmp_path
    _write_incoming(svc, zip_bytes=_zip_bytes("run.exe"))

    found = await svc.scan_incoming()

    assert len(found) == 1 and "error" in found[0]
    await db.close()
