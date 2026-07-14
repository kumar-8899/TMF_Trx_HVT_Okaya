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
